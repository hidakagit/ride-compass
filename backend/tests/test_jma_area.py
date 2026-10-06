"""`domain/jma_area.py`——区域のコードから、地域マスタの親子関係を辿って警報エリアを解決する。

入口は`resolve_area`。地域マスタは架空の区域で組み立てる。

ここで見ないもの:
- 地点から区域のコードを引くこと → `test_jma_area_boundaries.py`
- area.jsonの形を`AreaMaster`へ解くこと → `test_jma_warning_client.py`
"""

import pytest

from app.domain.jma_area import AreaEntry, AreaMaster, ResolvedArea, resolve_area

CLASS10 = {"130010": AreaEntry(parent="130000")}


def _master(class20s, class15s=None, class10s=None) -> AreaMaster:
    return AreaMaster(class20s=class20s, class15s=class15s or {}, class10s=class10s or CLASS10)


EXPECTED = ResolvedArea(class20_code="1310100", class10_code="130010", office_code="130000")


@pytest.mark.parametrize(
    ("parent", "class15s"),
    [
        ("130010", {}),
        ("a", {"a": AreaEntry(parent="b"), "b": AreaEntry(parent="130010")}),
    ],
    ids=["parent_is_already_the_subdivision", "several_class15_levels"],
)
def test_an_area_is_resolved_by_following_class15_parents_up_to_the_subdivision(parent, class15s):
    master = _master({"1310100": AreaEntry(parent=parent)}, class15s)
    assert resolve_area("1310100", master) == EXPECTED


@pytest.mark.parametrize(
    ("class20s", "class15s", "class10s"),
    [
        ({}, {}, CLASS10),
        ({"1310100": AreaEntry(parent=None)}, {}, CLASS10),
        ({"1310100": AreaEntry(parent="missing")}, {}, CLASS10),
        ({"1310100": AreaEntry(parent="a")}, {"a": AreaEntry(parent=None)}, CLASS10),
        (
            {"1310100": AreaEntry(parent="a")},
            {"a": AreaEntry(parent="b"), "b": AreaEntry(parent="a")},
            CLASS10,
        ),
        ({"1310100": AreaEntry(parent="130010")}, {}, {"130010": AreaEntry(parent=None)}),
    ],
    ids=[
        "area_missing_from_the_master",
        "area_without_parent",
        "parent_in_no_level",
        "class15_without_parent",
        "cycle",
        "subdivision_without_office",
    ],
)
def test_a_chain_that_cannot_reach_a_subdivision_with_an_office_is_unresolved(class20s, class15s, class10s):
    assert resolve_area("1310100", _master(class20s, class15s, class10s)) is None
