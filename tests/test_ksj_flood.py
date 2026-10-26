import io
import struct
import zipfile

import ksj_flood as k
import pytest


def test_parse_member_splits_the_name():
    d = k.parse_member("20_想定最大規模\\A31a-20-25_13_8303040044_10.shp")
    assert d["cat"] == "20" and d["area"] == "13" and d["river"] == "8303040044"
    assert d["group"] == "10" and d["ext"] == "shp"
    d = k.parse_member("42_家屋倒壊等氾濫想定区域_河岸侵食/A31a-42-25_83_8303050003_10.dbf")
    assert d["cat"] == "42" and d["ext"] == "dbf"


@pytest.mark.parametrize(
    "name",
    [
        "20_x\\A31a-10-25_13_1_10.shp",  # directory and file disagree on the category
        "99_x\\A31a-99-25_13_1_10.shp",  # unknown category
        "20_x\\A31a-20-25_13_1_30.shp",  # unknown group
        "20_x\\A31a-20-24_13_1_10.shp",  # not the FY2025 edition
        "readme.txt",
    ],
)
def test_parse_member_refuses_what_it_does_not_know(name):
    with pytest.raises(ValueError):
        k.parse_member(name)


def test_field_names_per_category():
    assert k.field_names("10") == ["A31a_101", "A31a_102", "A31a_103", "A31a_104", "A31a_105"]
    assert k.field_names("30")[4] == "A31a_305"
    assert k.field_names("41") == k.field_names("42")  # both erosion and flow use A31a_40x


def test_shp_members_demands_complete_sets():
    def mk(names):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            for n in names:
                z.writestr(n, b"x")
        return zipfile.ZipFile(io.BytesIO(b.getvalue()))

    base = "10_x/A31a-10-25_13_1_10"
    full = [base + e for e in (".shp", ".shx", ".dbf", ".prj")]
    assert k.shp_members(mk(full)) == [base + ".shp"]
    assert k.shp_members(mk(full + ["メタデータ\\KS-META-A31a-25_13_10.xml"])) == [base + ".shp"]
    with pytest.raises(ValueError):
        k.shp_members(mk(full[:3]))
    with pytest.raises(ValueError):
        k.shp_members(mk(full + ["extra.txt"]))


def test_bbox_of_shp_reads_the_header():
    head = bytearray(100)
    head[36:68] = struct.pack("<4d", 139.0, 35.0, 140.0, 36.0)
    assert k.bbox_of_shp(bytes(head)) == (139.0, 35.0, 140.0, 36.0)


def test_class_codes_cover_the_values_seen():
    assert set(k.WATER_DEPTH) == set(range(1, 7))
    assert set(k.FLOOD_DURATION) == set(range(1, 8))
    assert {c: v[2] for c, v in k.CATEGORIES.items()}["30"] == "flood_duration"
    assert len(k.WARD_CODES) == 23 and k.WARD_CODES[0] == "13101" and k.WARD_CODES[-1] == "13123"
