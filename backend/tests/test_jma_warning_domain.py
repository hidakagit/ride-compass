"""`domain/jma_warning.py`——警報・注意報の電文の1地域ぶんから、サイクリングに関わる発表中のものを取り出す。

入口は`extract_active_warnings`（種別→発表中の警報）・`warning_level`（種別の名称→警戒の段）・`WarningBulletin.kinds_for`
（電文から地点の種別を引く）。コード表`WARNING_KINDS`（配信元の資料の写し）は差し替えず、本物の表の行から種別を
組み立てる——どのコードが何の種別かには踏み込まない。

ここで見ないもの:
- 電文の形を`WarningBulletin`へ解くこと → `test_jma_warning_client.py`
- 地点から区域を引くこと・電文を全件走査して集めること → `test_warning_service.py`
"""

import pytest

from app.domain.jma_warning import (
    WARNING_KINDS,
    AreaWarningKind,
    WarningBulletin,
    extract_active_warnings,
    warning_level,
)

RELEVANT, OTHER_RELEVANT = [code for code, kind in WARNING_KINDS.items() if kind.relevant_to_cycling][:2]
IRRELEVANT = next(code for code, kind in WARNING_KINDS.items() if not kind.relevant_to_cycling)


def _kind(code: str | None, status: str | None = "発表", additions: tuple[str, ...] = ()) -> AreaWarningKind:
    return AreaWarningKind(code=code, status=status, additions=additions)


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


def _issued(code: str, additions: list[str]) -> dict:
    name = WARNING_KINDS[code].name
    return {"code": code, "name": name, "level": warning_level(name), "additions": additions}


def test_issued_and_continuing_warnings_come_out_in_order_with_their_name_level_and_additions():
    warnings = extract_active_warnings([_kind(OTHER_RELEVANT, "継続", ("土砂災害",)), _kind(RELEVANT, "発表")])

    assert [warning.model_dump() for warning in warnings] == [
        _issued(OTHER_RELEVANT, ["土砂災害"]),
        _issued(RELEVANT, []),
    ]


@pytest.mark.parametrize(
    "kind",
    [
        _kind(RELEVANT, "解除"),
        _kind(None, "発表警報・注意報はなし"),
        _kind(IRRELEVANT, "発表"),
        _kind("t_unknown", "発表"),
    ],
    ids=["lifted", "nothing_issued", "not_relevant_to_cycling", "missing_from_the_table"],
)
def test_lifted_absent_irrelevant_and_unknown_kinds_are_left_out(kind):
    assert extract_active_warnings([kind]) == []


AREA = (_kind("t_warning"),)
SUBDIVISION = (_kind("t_advisory"),)
NOTHING = (_kind(None, "発表警報・注意報はなし"),)


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
