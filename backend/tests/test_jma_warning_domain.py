from app.domain.jma_warning import (
    ACTIVE_STATUSES,
    CYCLING_RELEVANT_WARNING_CODES,
    WARNING_CODE_NAMES,
    extract_active_warnings,
    warning_level,
)


def test_active_statuses_excludes_cleared_and_none():
    assert "解除" not in ACTIVE_STATUSES
    assert "発表警報・注意報はなし" not in ACTIVE_STATUSES
    assert "発表" in ACTIVE_STATUSES
    assert "継続" in ACTIVE_STATUSES


def test_cycling_relevant_codes_excludes_out_of_scope_families():
    # 高潮(08/19/38/48)・乾燥(21)・その他の注意報(27)は道路走行との関連が薄く対象外。
    # 霜(24)・着氷(25)・着雪(26)・なだれ(22)・低温(23)はT206、濃霧(20)はT208で別途扱う。
    out_of_scope = {"08", "17", "19", "20", "21", "22", "23", "24", "25", "26", "27", "38", "48"}
    assert out_of_scope.isdisjoint(CYCLING_RELEVANT_WARNING_CODES)


def test_cycling_relevant_codes_includes_expected_families():
    # 大雨・洪水・暴風/強風・波浪・大雪・雷・土砂災害の各系統が入っていること。
    expected = {"03", "10", "33", "43", "04", "18", "05", "15", "07", "16", "06", "14", "09", "29"}
    assert expected.issubset(CYCLING_RELEVANT_WARNING_CODES)


def test_warning_level_classifies_three_tiers():
    assert warning_level("10") == "advisory"  # 大雨注意報
    assert warning_level("03") == "warning"  # 大雨警報
    assert warning_level("43") == "warning"  # 大雨危険警報（「警報」を含む）
    assert warning_level("33") == "emergency_warning"  # 大雨特別警報
    assert warning_level("99") == "advisory"  # 未知コードは名称が空文字のためadvisory側へ倒す


def test_extract_active_warnings_filters_inactive_and_irrelevant():
    kinds = [
        {"code": "14", "status": "発表", "additions": ["竜巻", "ひょう"]},  # 対象・発表中
        {"code": "20", "status": "発表"},  # 濃霧、対象外の種別
        {"code": "03", "status": "解除"},  # 対象だが解除済み
        {"status": "発表警報・注意報はなし"},  # codeキー自体が無い
    ]
    result = extract_active_warnings(kinds)
    assert [w.code for w in result] == ["14"]
    assert result[0].name == WARNING_CODE_NAMES["14"]
    assert result[0].level == "advisory"
    assert result[0].additions == ["竜巻", "ひょう"]


def test_extract_active_warnings_returns_empty_list_when_nothing_active():
    assert extract_active_warnings([{"status": "発表警報・注意報はなし"}]) == []


def test_extract_active_warnings_defaults_additions_to_empty_list():
    result = extract_active_warnings([{"code": "03", "status": "継続"}])
    assert result[0].additions == []
