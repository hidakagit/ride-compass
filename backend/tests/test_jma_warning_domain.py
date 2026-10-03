"""`domain/jma_warning.py`——警報・注意報の電文の1地域ぶんから、サイクリングに関わる発表中のものを取り出す。

入口は`extract_active_warnings`（種別→発表中の警報と、その警戒の段）・`WarningBulletin.kinds_for`
（電文から地点の種別を引く）。コード表`WARNING_KINDS`は配信元の資料の写し
（本番の正本を持つ宣言のデータ）なので中身に踏み込まず、架空のコードを足して与える。

ここで見ないもの:
- 電文の形を`WarningBulletin`へ解くこと → `test_jma_warning_client.py`
- 地点から区域を引くこと・電文を全件走査して集めること → `test_warning_service.py`
"""

import logging

import pytest

from app.domain import jma_warning
from app.domain.jma_warning import AreaWarningKind, WarningBulletin, WarningKind, extract_active_warnings

CODES = {
    "t_advisory": WarningKind("架空注意報"),
    "t_warning": WarningKind("架空警報"),
    "t_danger": WarningKind("架空危険警報"),
    "t_emergency": WarningKind("架空特別警報"),
    "t_irrelevant": WarningKind("架空の関わらない警報", relevant_to_cycling=False),
}


@pytest.fixture
def _codes(monkeypatch):
    for code, kind in CODES.items():
        monkeypatch.setitem(jma_warning.WARNING_KINDS, code, kind)


def _kind(code: str | None, status: str | None = "発表", additions: tuple[str, ...] = ()) -> AreaWarningKind:
    return AreaWarningKind(code=code, status=status, additions=additions)


@pytest.mark.usefixtures("_codes")
@pytest.mark.parametrize(
    ("code", "level"),
    [
        ("t_advisory", "advisory"),
        ("t_warning", "warning"),
        ("t_danger", "severe_warning"),
        ("t_emergency", "emergency_warning"),
    ],
)
def test_the_level_is_read_from_the_name(code, level):
    """危険警報（警戒レベル4）は警報と特別警報の間。どちらの名称も「警報」を含む。"""
    assert [warning.level for warning in extract_active_warnings([_kind(code)])] == [level]


@pytest.mark.usefixtures("_codes")
def test_issued_and_continuing_warnings_come_out_in_order_with_their_name_level_and_additions():
    warnings = extract_active_warnings([_kind("t_emergency", "継続", ("土砂災害",)), _kind("t_advisory", "発表")])

    assert [warning.model_dump() for warning in warnings] == [
        {"code": "t_emergency", "name": "架空特別警報", "level": "emergency_warning", "additions": ["土砂災害"]},
        {"code": "t_advisory", "name": "架空注意報", "level": "advisory", "additions": []},
    ]


@pytest.mark.usefixtures("_codes")
@pytest.mark.parametrize(
    "kind",
    [
        _kind("t_warning", "解除"),
        _kind(None, "発表警報・注意報はなし"),
        _kind("t_warning", None),
        _kind("t_irrelevant", "発表"),
    ],
    ids=["lifted", "nothing_issued", "no_status", "not_relevant_to_cycling"],
)
def test_lifted_absent_and_irrelevant_kinds_are_left_out(kind):
    assert extract_active_warnings([kind]) == []


@pytest.mark.usefixtures("_codes")
def test_an_issued_code_missing_from_the_table_is_left_out_with_a_warning(caplog):
    """表が配信元より古くなった印として、運用者に見えるように出す。"""
    with caplog.at_level(logging.WARNING, logger="ridecompass.jma_warning"):
        warnings = extract_active_warnings([_kind("t_unknown"), _kind("t_warning")])

    assert [warning.code for warning in warnings] == ["t_warning"]
    assert any("t_unknown" in record.getMessage() for record in caplog.records)


AREA = (_kind("t_warning"),)
SUBDIVISION = (_kind("t_advisory"),)
NOTHING = (_kind(None, "発表警報・注意報はなし"),)


@pytest.mark.parametrize(
    ("class20_kinds", "class10_kinds", "expected"),
    [
        ({"1310100": AREA}, {"130010": SUBDIVISION}, AREA),
        ({"1310100": NOTHING}, {"130010": SUBDIVISION}, NOTHING),
        ({}, {"130010": SUBDIVISION}, SUBDIVISION),
        ({"1310200": AREA}, {"130020": SUBDIVISION}, None),
    ],
    ids=["area_first", "area_saying_nothing_still_wins", "subdivision_when_no_area_item", "neither"],
)
def test_the_area_item_is_used_and_the_subdivision_only_when_the_bulletin_has_no_area_item(
    class20_kinds, class10_kinds, expected
):
    bulletin = WarningBulletin(report_datetime=None, class20_kinds=class20_kinds, class10_kinds=class10_kinds)
    assert bulletin.kinds_for("1310100", "130010") == expected
