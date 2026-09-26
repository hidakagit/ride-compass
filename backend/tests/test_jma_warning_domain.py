"""`domain/jma_warning.py`——警報・注意報のコードの段と、1地域ぶんの発表中の警報の取り出し。

ここで見ないもの:
- 電文を種別へ解く → `test_jma_warning_client.py`
- 地点の区域の解決と電文をまたいだ集約 → `test_warning_service.py`
- 段の色・呼び名 → `domain/warning_display.py`

段の期待値は、コードの表を読み直して作らない（名称に「特別警報」を含むか、と同じ規則で期待値を
作ると恒真になる）。気象庁の別表3が決めている段を、代表のコードで突き合わせる。
"""

import pytest

from app.domain import jma_warning


# ---- コードの段（気象庁の別表3） ----


@pytest.mark.parametrize(
    ("code", "level"),
    [
        ("33", "emergency_warning"),  # 大雨特別警報（警戒レベル5）
        ("43", "severe_warning"),  # 大雨危険警報（警戒レベル4）
        ("49", "severe_warning"),  # 土砂災害危険警報（警戒レベル4）
        ("03", "warning"),  # 大雨警報
        ("10", "advisory"),  # 大雨注意報
        ("14", "advisory"),  # 雷注意報
    ],
)
def test_the_badge_level_follows_the_official_code_table(code, level):
    assert jma_warning.warning_level(code) == level


def test_a_code_not_in_the_table_is_an_error():
    with pytest.raises(KeyError):
        jma_warning.warning_level("no_such_code")


# ---- 発表中の警報の取り出し ----


def _relevant_code() -> str:
    return next(code for code, kind in jma_warning.WARNING_KINDS.items() if kind.relevant_to_cycling)


def _kind(code: str | None, status: str | None = "発表", additions: tuple[str, ...] = ()) -> jma_warning.AreaWarningKind:
    return jma_warning.AreaWarningKind(code=code, status=status, additions=additions)


@pytest.mark.parametrize("status", sorted(jma_warning.ACTIVE_STATUSES))
def test_an_issued_or_continuing_warning_is_taken_with_its_name_level_and_additions(status):
    code = _relevant_code()

    (warning,) = jma_warning.extract_active_warnings([_kind(code, status, ("土砂災害",))])

    assert warning == jma_warning.ActiveWarning(
        code=code,
        name=jma_warning.WARNING_KINDS[code].name,
        level=jma_warning.warning_level(code),
        additions=["土砂災害"],
    )


@pytest.mark.parametrize("status", ["解除", "発表警報・注意報はなし", None])
def test_a_warning_that_is_not_in_force_is_left_out(status):
    assert jma_warning.extract_active_warnings([_kind(_relevant_code(), status)]) == []


def test_an_area_with_nothing_issued_has_no_code_and_gives_nothing():
    assert jma_warning.extract_active_warnings([_kind(None, "発表警報・注意報はなし")]) == []


def test_a_code_not_in_the_table_is_left_out():
    assert jma_warning.extract_active_warnings([_kind("no_such_code")]) == []


def test_every_kind_not_relevant_to_cycling_is_left_out():
    hidden = [code for code, kind in jma_warning.WARNING_KINDS.items() if not kind.relevant_to_cycling]
    assert hidden, "出さない種別が1つも無い"

    assert jma_warning.extract_active_warnings([_kind(code) for code in hidden]) == []


def test_warnings_keep_the_order_they_came_in():
    shown = [code for code, kind in jma_warning.WARNING_KINDS.items() if kind.relevant_to_cycling][:3]
    kinds = [_kind(code) for code in reversed(shown)]

    assert [w.code for w in jma_warning.extract_active_warnings(kinds)] == list(reversed(shown))
