"""Write GeoParquet of the flood inundation polygons that touch the 23 wards of Tokyo.

Reads the Shapefile zips of the FY2025 edition of A31a under data/raw/<version>/ and keeps every
polygon that intersects the 23 wards (the boundary is N03 of 2026-01-01, used only to select; it is
not republished). The polygons are written as they are in the source, not clipped. One row per
polygon: id, category (planned / maximum / duration / collapse_flow / collapse_erosion), river_code,
river_name, manager_code, manager (the A31a_x01..x04 of the source), class_code (A31a_x05: the
rank of depth or duration, or the kind of the collapse area), river_group (10: 洪水予報河川・水位周知
河川, 20: その他の河川), source_zip, source_member, source_index, geometry (WKB Polygon, EPSG:6668).
data/parquet/flood_area.parquet holds all rows; data/parquet/categories/<category>.parquet one
category. The zips that are only checked (data/docs/checked/) must give no polygon in the wards.

    uv run python scripts/02_export_parquet.py [--version 2026-10-26]
"""

import argparse
import io
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

import ksj_flood as k
import pyarrow as pa
import pyarrow.parquet as pq
import shapefile
from pyproj import CRS
from shapely import prepare, set_precision  # noqa: F401
from shapely.geometry import box, shape
from shapely.ops import unary_union

ROOT = Path(__file__).parents[1]
SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("category", pa.string()),
        ("river_code", pa.string()),
        ("river_name", pa.string()),
        ("manager_code", pa.string()),
        ("manager", pa.string()),
        ("class_code", pa.int8()),
        ("river_group", pa.string()),
        ("source_zip", pa.string()),
        ("source_member", pa.string()),
        ("source_index", pa.int32()),
        ("geometry", pa.binary()),
    ]
)


def wards(n03_zip: Path):
    """Union of the 23 wards from the N03 Shapefile (UTF-8 dbf), as a prepared geometry."""
    with zipfile.ZipFile(n03_zip) as z:
        stem = next(n[:-4] for n in z.namelist() if n.endswith(".shp"))
        sf = shapefile.Reader(
            shp=io.BytesIO(z.read(stem + ".shp")), shx=io.BytesIO(z.read(stem + ".shx")),
            dbf=io.BytesIO(z.read(stem + ".dbf")), encoding="utf-8")  # fmt: skip
    geoms, found = [], set()
    for sr in sf.iterShapeRecords():
        code = sr.record.as_dict()["N03_007"]
        if code in k.WARD_CODES:
            geoms.append(shape(sr.shape.__geo_interface__))
            found.add(code)
    if found != set(k.WARD_CODES):
        raise SystemExit(f"wards missing from N03: {sorted(set(k.WARD_CODES) - found)}")
    u = unary_union(geoms)
    prepare(u)
    return u


def scan(zip_path: Path, area, area_box, emit) -> Counter:
    """Call emit(zip, member, index, attrs, geometry) for each polygon touching the area."""
    stats = Counter()
    with k.open_zip(zip_path) as z:
        for member in k.shp_members(z):
            info = k.parse_member(member)
            stats["members"] += 1
            base = member[:-4]
            shp = z.read(member)
            xmin, ymin, xmax, ymax = k.bbox_of_shp(shp[:100])
            if not box(xmin, ymin, xmax, ymax).intersects(area_box):
                stats["members_outside"] += 1
                continue
            sf = shapefile.Reader(
                shp=io.BytesIO(shp), shx=io.BytesIO(z.read(base + ".shx")),
                dbf=io.BytesIO(z.read(base + ".dbf")), encoding="cp932")  # fmt: skip
            prj = z.read(base + ".prj").decode()
            assert "JGD_2011" in prj or "JGD2011" in prj, prj[:80]
            names = [f[0] for f in sf.fields[1:]]
            if names != k.field_names(info["cat"]):
                raise ValueError(f"{member}: unexpected fields {names}")
            if sf.shapeTypeName != "POLYGON":
                raise ValueError(f"{member}: {sf.shapeTypeName}")
            for i, sr in enumerate(sf.iterShapeRecords()):
                stats["polygons_scanned"] += 1
                x0, y0, x1, y1 = sr.shape.bbox
                if not box(x0, y0, x1, y1).intersects(area_box):
                    continue
                g = shape(sr.shape.__geo_interface__)
                if area.intersects(g):
                    stats["polygons_kept"] += 1
                    emit(zip_path.name, member, i, info, list(sr.record), g)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=None)
    a = ap.parse_args()
    runs = sorted((ROOT / "data" / "raw").glob("*/MANIFEST.json"))
    raw = runs[-1].parent if a.version is None else ROOT / "data" / "raw" / a.version
    manifest = json.loads((raw / "MANIFEST.json").read_text())
    docs = ROOT / "data" / "docs"
    area = wards(docs / Path(k.N03_URL).name)
    area_box = box(*area.bounds)
    rows: list[dict] = []
    invalid = Counter()

    def emit(zname, member, i, info, rec, g):
        code, name, mcode, mname, cls = rec
        _, _, codelist = k.CATEGORIES[info["cat"]]
        if int(cls) not in k.CLASS_CODES[codelist]:
            raise ValueError(f"{member}[{i}]: class code {cls} is not in the code list")
        if g.geom_type != "Polygon":
            raise ValueError(f"{member}[{i}]: {g.geom_type}")
        if not g.is_valid:
            invalid[info["cat"]] += 1
        slug = k.CATEGORIES[info["cat"]][0]
        rows.append({
            "id": f"{info['area']}-{info['group']}-{info['cat']}-{info['river']}-{i:06d}",
            "category": slug, "river_code": code, "river_name": name, "manager_code": mcode,
            "manager": mname, "class_code": int(cls), "river_group": info["group"],
            "source_zip": zname, "source_member": member, "source_index": i, "geometry": g.wkb,
        })  # fmt: skip

    per_zip = {}
    for name, meta in manifest["files"].items():
        if meta["role"] != "used":
            continue
        per_zip[name] = dict(scan(raw / name, area, area_box, emit))
        print(name, per_zip[name], flush=True)
    checked = {}
    for name, meta in manifest["files"].items():
        if meta["role"] != "checked":
            continue
        checked[name] = dict(scan(docs / "checked" / name, area, area_box, lambda *_: None))
        print("checked", name, checked[name], flush=True)
        if checked[name].get("polygons_kept", 0):
            raise SystemExit(f"{name}: polygons in the wards; move it to 'used'")
    if not rows:
        raise SystemExit("no polygon found")
    crs = CRS.from_epsg(k.EPSG).to_json_dict()
    geo = {
        "version": "1.1.0", "primary_column": "geometry",
        "columns": {"geometry": {"encoding": "WKB", "geometry_types": ["Polygon"], "crs": crs}},
    }  # fmt: skip
    par = ROOT / "data" / "parquet"
    (par / "categories").mkdir(parents=True, exist_ok=True)

    def write(rs, path):
        t = pa.Table.from_pylist(rs, schema=SCHEMA).replace_schema_metadata(
            {b"geo": json.dumps(geo).encode()}
        )
        pq.write_table(t, path, compression="zstd", row_group_size=50_000)

    write(rows, par / "flood_area.parquet")
    by_cat = Counter(r["category"] for r in rows)
    for slug in by_cat:
        write([r for r in rows if r["category"] == slug], par / "categories" / f"{slug}.parquet")
    (par / "columns.json").write_text(
        json.dumps({
            "run": raw.name, "rows": len(rows), "by_category": dict(by_cat),
            "by_zip": per_zip, "checked_zips": checked,
            "invalid_geometries": dict(invalid), "crs": f"EPSG:{k.EPSG}",
            "classes": {n: {str(c): v for c, v in d.items()} for n, d in k.CLASS_CODES.items()},
            "categories": {c: {"slug": s, "name": n, "class": cl} for c, (s, n, cl) in k.CATEGORIES.items()},
            "river_groups": k.GROUPS,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")  # fmt: skip
    print(len(rows), dict(by_cat))
    return 0


if __name__ == "__main__":
    sys.exit(main())
