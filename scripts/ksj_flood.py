"""Shared helpers: the files of 国土数値情報 洪水浸水想定区域 (河川単位, A31a, FY2025 edition) and how to read them."""

import re
import zipfile

BASE = "https://nlftp.mlit.go.jp/ksj/gml/data/A31a/A31a-25/"
PAGE_URL = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31a-2025.html"
TERMS_URL = "https://nlftp.mlit.go.jp/ksj/other/agreement_01.html"
RIVER_LIST_URL = "https://nlftp.mlit.go.jp/ksj/gml/codelist/A31_R7_datalist.xlsx"
CODELIST_URLS = {
    "water_depth_code.xlsx": "https://nlftp.mlit.go.jp/ksj/gml/codelist/water_depth_code.xlsx",
    "flood_duration_code.xlsx": "https://nlftp.mlit.go.jp/ksj/gml/codelist/flood_duration_code.xlsx",
    "hazardous_area_classification_code.xlsx": "https://nlftp.mlit.go.jp/ksj/gml/codelist/hazardous_area_classification_code.xlsx",
    "CreatingTypeCd.xlsx": "https://nlftp.mlit.go.jp/ksj/gml/codelist/CreatingTypeCd.xlsx",
}
N03_URL = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2026/N03-20260101_13_GML.zip"
N03_PAGE_URL = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html"
EPSG = 6668  # JGD2011, as the .prj of the source states

# Zips that hold polygons in the 23 wards (role "used"), and zips whose rivers the source's river
# list marks as reaching the 1st-level mesh 5339 (the mesh of the 23 wards) but in which no polygon
# falls in the wards (role "checked": read to show that, not published). Tokyo (13), Saitama (11)
# and the Kanto bureau (83) hold the polygons; Chiba, Kanagawa, Ibaraki, Yamanashi and Shizuoka do not.
USED = ["13_10", "13_20", "83_10", "11_10", "11_20"]
CHECKED = ["12_10", "12_20", "14_10", "14_20", "08_10", "08_20", "19_10", "19_20", "22_10", "22_20"]

# The 23 wards: 全国地方公共団体コード without the check digit, as N03_007 gives it.
WARD_CODES = [f"131{i:02d}" for i in range(1, 24)]

# category prefix (the number in the member name) -> (slug, Japanese name, code list of the class)
CATEGORIES = {
    "10": ("planned", "計画規模", "water_depth"),
    "20": ("maximum", "想定最大規模", "water_depth"),
    "30": ("duration", "浸水継続時間", "flood_duration"),
    "41": ("collapse_flow", "家屋倒壊等氾濫想定区域（氾濫流）", "hazardous_area"),
    "42": ("collapse_erosion", "家屋倒壊等氾濫想定区域（河岸浸食）", "hazardous_area"),
}
GROUPS = {"10": "洪水予報河川・水位周知河川", "20": "その他の河川"}
WATER_DEPTH = {
    1: "0〜0.5m未満", 2: "0.5〜3.0m未満", 3: "3.0〜5.0m未満",
    4: "5.0〜10.0m未満", 5: "10.0〜20.0m未満", 6: "20.0m以上",
}  # fmt: skip
FLOOD_DURATION = {
    1: "12時間未満", 2: "12時間〜24時間未満", 3: "24時間〜72時間未満",
    4: "72時間〜168時間未満", 5: "168時間〜336時間未満", 6: "336時間〜672時間未満",
    7: "672時間以上",
}  # fmt: skip
HAZARDOUS_AREA = {1: "氾濫流", 2: "河岸浸食"}
CLASS_CODES = {
    "water_depth": WATER_DEPTH,
    "flood_duration": FLOOD_DURATION,
    "hazardous_area": HAZARDOUS_AREA,
}

MEMBER_RE = re.compile(
    r"^(?P<dir>\d\d)_[^\\/]+[\\/]A31a-(?P<cat>\d\d)-25_(?P<area>\d\d)_(?P<river>\d+)_(?P<group>\d\d)\.(?P<ext>shp|shx|dbf|prj)$"
)


def zip_name(area_group: str) -> str:
    return f"A31a-25_{area_group}_SHP.zip"


def open_zip(path) -> zipfile.ZipFile:
    """The member names of the source are cp932 (the directory names are Japanese)."""
    return zipfile.ZipFile(path, metadata_encoding="cp932")


def parse_member(name: str) -> dict:
    """Split a member name such as `20_想定最大規模\\A31a-20-25_13_8303040044_10.shp`."""
    m = MEMBER_RE.match(name)
    if m is None:
        raise ValueError(f"unexpected member name {name!r}")
    d = m.groupdict()
    if d["dir"] != d["cat"] or d["cat"] not in CATEGORIES or d["group"] not in GROUPS:
        raise ValueError(f"unexpected member name {name!r}")
    return d


def shp_members(z: zipfile.ZipFile) -> list[str]:
    """The .shp members (the KS-META xml aside), checking that every other member is the .shx/.dbf/.prj of one of them."""
    names = [
        n for n in z.namelist() if not n.endswith(("/", "\\")) and "KS-META-" not in n
    ]  # the metadata xml sits in its own directory, メタデータ
    shp = sorted(n for n in names if n.endswith(".shp"))
    expected = {n[:-4] + e for n in shp for e in (".shp", ".shx", ".dbf", ".prj")}
    if set(names) != expected:
        raise ValueError(
            f"members that are not shp/shx/dbf/prj sets: {sorted(set(names) ^ expected)[:5]}"
        )
    return shp


def field_names(cat: str) -> list[str]:
    """The five attributes of a layer: river code, river name, manager code, manager, class."""
    p = {"10": "1", "20": "2", "30": "3", "41": "4", "42": "4"}[cat]
    return [f"A31a_{p}0{i}" for i in range(1, 6)]


def bbox_of_shp(head: bytes) -> tuple[float, float, float, float]:
    """The bounding box (xmin, ymin, xmax, ymax) in the 100-byte header of a .shp."""
    import struct

    return struct.unpack("<4d", head[36:68])
