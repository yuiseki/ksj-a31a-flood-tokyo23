"""Check the Parquet against the Shapefile zips as served, by a second route.

02_export_parquet.py skips a member when its header box and then a polygon when its own box does
not touch the 23 wards. Here every polygon of every zip (the checked zips too) is tested with
`intersects` on the prepared ward union, with no box pre-filter, and the set of (zip, member,
index) must equal the Parquet's exactly. For each kept polygon the five attributes and the
coordinates (to 0, as WKB) equal the .dbf (read as cp932) and the .shp. Also: ids are unique, the
category files are the all-categories file split by category, the crs is PROJJSON, every river code
carries a river name that the source's river list gives it (its 河川名 or 河川名補足), and the class codes are in the code
lists. The zips that are only checked must give no polygon in the wards.

    uv run python scripts/03_verify.py
"""

import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import ksj_flood as k
import numpy as np
import openpyxl
import pyarrow as pa
import pyarrow.parquet as pq
import shapefile
import shapely
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).parent))
from importlib import import_module  # noqa: E402

ROOT = Path(__file__).parents[1]


def river_names(xlsx: Path) -> dict[str, set[str]]:
    wb = openpyxl.load_workbook(xlsx, read_only=True)
    out = defaultdict(set)
    for ws in list(wb)[3:]:
        for i, r in enumerate(ws.iter_rows(values_only=True)):
            if i and r[5] and r[7]:
                out[str(r[5])].add(str(r[7]))
                if r[8]:  # 河川名補足: some layers of the source use it as the river name
                    out[str(r[5])].add(str(r[8]))
    return out


def main() -> int:
    run = sorted((ROOT / "data" / "raw").glob("*/MANIFEST.json"))[-1].parent
    manifest = json.loads((run / "MANIFEST.json").read_text())
    docs = ROOT / "data" / "docs"
    par = ROOT / "data" / "parquet"
    exp = import_module("02_export_parquet")
    area = exp.wards(docs / Path(k.N03_URL).name)
    shapely.prepare(area)
    allt = pq.read_table(par / "flood_area.parquet")
    geo = json.loads(allt.schema.metadata[b"geo"])
    crs = geo["columns"]["geometry"]["crs"]
    assert isinstance(crs, dict) and crs["id"]["code"] == k.EPSG, "crs must be PROJJSON 6668"
    d = allt.to_pydict()
    n = allt.num_rows
    assert len(set(d["id"])) == n, "ids are not unique"
    row_of = {
        (d["source_zip"][i], d["source_member"][i], d["source_index"][i]): i for i in range(n)
    }
    assert len(row_of) == n
    seen = set()
    for name, meta in manifest["files"].items():
        if meta["role"] not in ("used", "checked"):
            continue
        path = (run if meta["role"] == "used" else docs / "checked") / name
        kept = 0
        with k.open_zip(path) as z:
            for member in k.shp_members(z):
                info = k.parse_member(member)
                base = member[:-4]
                sf = shapefile.Reader(
                    shp=io.BytesIO(z.read(member)), shx=io.BytesIO(z.read(base + ".shx")),
                    dbf=io.BytesIO(z.read(base + ".dbf")), encoding="cp932")  # fmt: skip
                if len(sf) == 0:
                    continue
                shapes = sf.shapes()
                geoms = np.array([shape(s.__geo_interface__) for s in shapes], dtype=object)
                hit = np.nonzero(shapely.intersects(geoms, area))[0]
                for i in hit:
                    kept += 1
                    key = (name, member, int(i))
                    seen.add(key)
                    assert key in row_of, f"polygon missing from the Parquet: {key}"
                    r = row_of[key]
                    rec = list(sf.record(int(i)))
                    got = [
                        d["river_code"][r],
                        d["river_name"][r],
                        d["manager_code"][r],
                        d["manager"][r],
                        d["class_code"][r],
                    ]
                    assert got == [rec[0], rec[1], rec[2], rec[3], int(rec[4])], key
                    assert d["category"][r] == k.CATEGORIES[info["cat"]][0]
                    assert d["river_group"][r] == info["group"]
                    assert d["geometry"][r] == geoms[i].wkb, f"coordinates differ: {key}"
        print(f"{name} ({meta['role']}): {kept} polygons in the wards", flush=True)
        if meta["role"] == "checked":
            assert kept == 0, f"{name} has polygons in the wards"
    assert seen == set(row_of), (
        f"{len(set(row_of) - seen)} rows of the Parquet are not found by the second route"
    )
    # category files are the all-file split by category
    for slug in {c[0] for c in k.CATEGORIES.values()}:
        t = pq.read_table(par / "categories" / f"{slug}.parquet")
        want = allt.filter(pa.compute.equal(allt["category"], slug))
        assert t.equals(want), slug
    names = river_names(docs / "A31_R7_datalist.xlsx")
    bad = {
        (c, nm)
        for c, nm in zip(d["river_code"], d["river_name"], strict=True)
        if nm not in names.get(c, set())
    }
    assert not bad, f"river names that differ from the source's river list: {sorted(bad)[:5]}"
    cols = json.loads((par / "columns.json").read_text())
    assert cols["rows"] == n and cols["by_category"] == dict(Counter(d["category"]))
    print(f"OK: {n} polygons; the second route finds the same set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
