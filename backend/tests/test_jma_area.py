"""`domain/jma_area.py`——区域のコードから、地域マスタの親子関係を辿って警報エリアを解決する。

入口は`resolve_area`。地域マスタは架空の区域で組み立てる。

ここで見ないもの:
- 地点から区域のコードを引くこと → `test_jma_area_boundaries.py`
- area.jsonの形を`AreaMaster`へ解くこと → `test_jma_warning_client.py`
"""

import logging

import pytest

from app.domain.jma_area import AreaEntry, AreaMaster, ResolvedArea, resolve_area

CLASS10 = {"130010": AreaEntry(parent="130000", name="東京地方")}


def _master(class20s, class15s=None, class10s=None) -> AreaMaster:
    return AreaMaster(class20s=class20s, class15s=class15s or {}, class10s=class10s or CLASS10)


EXPECTED = ResolvedArea(class20_code="1310100", class10_code="130010", office_code="130000", class10_name="東京地方")


@pytest.mark.parametrize(
    ("parent", "class15s"),
    [
        ("130010", {}),
        ("a", {"a": AreaEntry(parent="b", name=None), "b": AreaEntry(parent="130010", name=None)}),
    ],
    ids=["parent_is_already_the_subdivision", "several_class15_levels"],
)
def test_an_area_is_resolved_by_following_class15_parents_up_to_the_subdivision(parent, class15s):
    master = _master({"1310100": AreaEntry(parent=parent, name=None)}, class15s)
    assert resolve_area("1310100", master) == EXPECTED


def test_an_area_missing_from_the_master_is_unresolved_with_a_warning(caplog):
    """区域の境界と地域マスタは別々に配られ、片方だけが区域の変更に追いつくと起きる。"""
    with caplog.at_level(logging.WARNING, logger="ridecompass.jma_area"):
        assert resolve_area("1310100", _master({})) is None
    assert any("1310100" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    ("class20s", "class15s", "class10s"),
    [
        ({"1310100": AreaEntry(parent=None, name="千代田区")}, {}, CLASS10),
        ({"1310100": AreaEntry(parent="missing", name="千代田区")}, {}, CLASS10),
        ({"1310100": AreaEntry(parent="a", name=None)}, {"a": AreaEntry(parent=None, name=None)}, CLASS10),
        (
            {"1310100": AreaEntry(parent="a", name=None)},
            {"a": AreaEntry(parent="b", name=None), "b": AreaEntry(parent="a", name=None)},
            CLASS10,
        ),
        ({"1310100": AreaEntry(parent="130010", name=None)}, {}, {"130010": AreaEntry(parent=None, name="東京地方")}),
        ({"1310100": AreaEntry(parent="130010", name=None)}, {}, {"130010": AreaEntry(parent="130000", name=None)}),
    ],
    ids=[
        "area_without_parent",
        "parent_in_no_level",
        "class15_without_parent",
        "cycle",
        "subdivision_without_office",
        "subdivision_without_name",
    ],
)
def test_a_chain_that_cannot_reach_a_named_subdivision_with_an_office_is_unresolved(class20s, class15s, class10s):
    assert resolve_area("1310100", _master(class20s, class15s, class10s)) is None
