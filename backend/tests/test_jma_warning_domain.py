"""`domain/jma_warning.py`——警報・注意報の電文の1地域ぶんから、サイクリングに関わる発表中のものを取り出す。

入口は`extract_active_warnings`（種別→発表中の警報）・`warning_level`（種別の名称→警戒の段）・`WarningBulletin.kinds_for`
（電文から地点の種別を引く）。出さない種別の表`NOT_RELEVANT_TO_CYCLING`は差し替えず、本物の表の名称から種別を
組み立てる——どの種別を出さないかには踏み込まない。

ここで見ないもの:
- 電文の形を`WarningBulletin`へ解くこと・コードを種別の名称へ、状態を発表中かへ読み替えること → `test_jma_warning_client.py`
- 地点から区域を引くこと・電文を全件走査して集めること → `test_warning_service.py`
"""

import pytest

from app.domain.jma_warning import (
    NOT_RELEVANT_TO_CYCLING,
    AreaWarningKind,
    WarningBulletin,
    extract_active_warnings,
    warning_level,
)

IRRELEVANT = min(NOT_RELEVANT_TO_CYCLING)


def _kind(name: str, active: bool = True, additions: tuple[str, ...] = (), code: str = "t_code") -> AreaWarningKind:
    return AreaWarningKind(code=code, name=name, active=active, additions=additions)


@pytest.mark.parametrize(
    ("name", "level"),
    [
        ("架空注意報", "advisory"),
        ("架空警報", "warning"),
        ("架空危険警報", "severe_warning"),
        ("架空特別警報", "emergency_warning"),
    ],
)
def test_the_level_is_read_from_the_name(name, level):
    """危険警報（警戒レベル4）は警報と特別警報の間。どちらの名称も「警報」を含む。"""
    assert warning_level(name) == level


def test_active_warnings_come_out_in_order_with_their_code_name_level_and_additions():
    """出さない表に無い名称は出す——配信元が新しい種別を出したとき、黙って隠さない。"""
    warnings = extract_active_warnings([_kind("架空警報", additions=("土砂災害",), code="t1"), _kind("架空注意報", code="t2")])

    assert [warning.model_dump() for warning in warnings] == [
        {"code": "t1", "name": "架空警報", "level": "warning", "additions": ["土砂災害"]},
        {"code": "t2", "name": "架空注意報", "level": "advisory", "additions": []},
    ]


@pytest.mark.parametrize(
    "kind",
    [_kind("架空警報", active=False), _kind(IRRELEVANT)],
    ids=["lifted", "not_relevant_to_cycling"],
)
def test_lifted_and_irrelevant_kinds_are_left_out(kind):
    assert extract_active_warnings([kind]) == []


AREA = (_kind("架空警報"),)
SUBDIVISION = (_kind("架空注意報"),)
NOTHING: tuple[AreaWarningKind, ...] = ()


@pytest.mark.parametrize(
    ("class20_kinds", "class10_kinds", "expected"),
    [
        ({"1310100": NOTHING}, {"130010": SUBDIVISION}, NOTHING),
        ({}, {"130010": SUBDIVISION}, SUBDIVISION),
        ({"1310200": AREA}, {"130020": SUBDIVISION}, None),
    ],
    ids=["area_first_even_saying_nothing", "subdivision_when_no_area_item", "neither"],
)
def test_the_area_item_is_used_and_the_subdivision_only_when_the_bulletin_has_no_area_item(
    class20_kinds, class10_kinds, expected
):
    bulletin = WarningBulletin(class20_kinds=class20_kinds, class10_kinds=class10_kinds)
    assert bulletin.kinds_for("1310100", "130010") == expected
