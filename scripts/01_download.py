"""Download the flood inundation areas (A31a, FY2025 edition) that reach the 23 wards of Tokyo.

Fetches, one second apart (403 or 429 stops the run): the Shapefile zips of Tokyo (13), its three
neighbouring prefectures (11, 12, 14) and the Kanto Regional Development Bureau (83), which hold
the polygons; the zips of three other prefectures whose rivers the source's river list marks as
reaching the 1st-level mesh of the 23 wards (08, 19, 22), only to show that nothing of them falls in
the wards; and the ward boundaries (N03, to select the polygons, not republished). Each file is
hashed and recorded (the zips that are only checked and the ward boundaries stay under data/docs/, which is not published) in data/raw/<version>/MANIFEST.json with the Last-Modified the server states.
The data page, the terms, the river list and the code lists are saved under data/docs/.

    uv run python scripts/01_download.py [--version 2026-10-26]
"""

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import ksj_flood as k

ROOT = Path(__file__).parents[1]
UA = "ksj-a31a-flood-tokyo23/0.1 (+https://github.com/yuiseki/ksj-a31a-flood-tokyo23)"


def fetch(url: str, dest: Path) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    h = hashlib.sha256()
    n = 0
    try:
        with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
            lm = r.headers.get("Last-Modified")
            while chunk := r.read(1 << 20):
                f.write(chunk)
                h.update(chunk)
                n += len(chunk)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise SystemExit(f"{e.code} from {url}: stopping") from e
        raise
    return {"url": url, "bytes": n, "sha256": h.hexdigest(), "last_modified": lm}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=dt.datetime.now(dt.UTC).strftime("%Y-%m-%d"))
    a = ap.parse_args()
    raw = ROOT / "data" / "raw" / a.version
    docs = ROOT / "data" / "docs"
    raw.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    pages = {"KsjTmplt-A31a-2025.html": k.PAGE_URL, "agreement_01.html": k.TERMS_URL,
             "A31_R7_datalist.xlsx": k.RIVER_LIST_URL, "KsjTmplt-N03-2026.html": k.N03_PAGE_URL,
             **k.CODELIST_URLS}  # fmt: skip
    for name, url in pages.items():
        time.sleep(1)
        fetch(url, docs / name)
    files = {}
    jobs = [(k.zip_name(c), k.BASE + k.zip_name(c), "used") for c in k.USED]
    jobs += [(k.zip_name(c), k.BASE + k.zip_name(c), "checked") for c in k.CHECKED]
    jobs += [(Path(k.N03_URL).name, k.N03_URL, "selection")]
    for name, url, role in jobs:
        time.sleep(1)
        dest = {"used": raw, "checked": docs / "checked", "selection": docs}[role] / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        files[name] = {**fetch(url, dest), "role": role}
        print(role, name, files[name]["bytes"], flush=True)
    (raw / "MANIFEST.json").write_text(
        json.dumps({"retrieved": a.version, "page": k.PAGE_URL, "files": files},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
