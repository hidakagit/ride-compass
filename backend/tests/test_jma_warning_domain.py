"""`domain/jma_warning.py`——気象庁の警報コードを、走行に関わるものだけへ絞る。

電文の取得・地域の解決は`test_weather_route.py`・`test_jma_area.py`が持つ。
コード表そのものは書き写さず、全件に対して成り立つことだけを見る。
"""

from app.domain.jma_warning import (
    ACTIVE_STATUSES,
    CYCLING_RELEVANT_WARNING_CODES,
    WARNING_CODE_NAMES,
    extract_active_warnings,
    warning_level,
)


class TestWarningLevel:
    """レベルは**名称から導く**。別テーブルで持つと、コードを1つ足したときに片方だけ
    古いまま残る。"""

    def test_a_special_warning_is_the_heaviest(self):
        special = [c for c, n in WARNING_CODE_NAMES.items() if "特別警報" in n]

        assert special
        for code in special:
            assert warning_level(code) == "emergency_warning", code

    def test_a_plain_warning_sits_between(self):
        warnings = [c for c, n in WARNING_CODE_NAMES.items() if n.endswith("警報") and "特別" not in n]

        assert warnings
        for code in warnings:
            assert warning_level(code) == "warning", code

    def test_an_advisory_is_the_lightest(self):
        advisories = [c for c, n in WARNING_CODE_NAMES.items() if n.endswith("注意報")]

        assert advisories
        for code in advisories:
            assert warning_level(code) == "advisory", code

    def test_an_unknown_code_falls_to_the_lightest(self):
        """知らないコードで赤いバッジを出さない。電文が増えても表示が壊れない側へ倒す。"""
        assert warning_level("99") == "advisory"

    def test_the_names_do_not_repeat_the_level(self):
        """名称に「レベルN」を残すと、同じ情報を名称とレベルの2箇所で持つことになる。"""
        for code, name in WARNING_CODE_NAMES.items():
            assert "レベル" not in name, code


class TestCyclingRelevantCodes:
    def test_every_selected_code_has_a_name(self):
        """名前を引けないコードを選ぶと、バッジにコード番号がそのまま出る。"""
        assert CYCLING_RELEVANT_WARNING_CODES
        for code in CYCLING_RELEVANT_WARNING_CODES:
            assert code in WARNING_CODE_NAMES, code

    def test_the_release_code_is_not_a_warning_to_show(self):
        """「解除」は発表の取り下げで、出すものが無い。"""
        assert "00" not in CYCLING_RELEVANT_WARNING_CODES

    def test_every_code_of_a_relevant_family_is_selected(self):
        """主対象は大雨・洪水・暴風/強風・波浪・大雪・雷と、山間部の通行可否に直結する
        土砂災害。同じ種別でも注意報・警報・特別警報・危険警報と段が分かれており、
        1段でも漏らすとその強さのときだけバッジが消える。
        """
        families = ("大雨", "洪水", "暴風", "強風", "波浪", "大雪", "雷", "土砂災害")
        expected = {c for c, n in WARNING_CODE_NAMES.items() if any(f in n for f in families)}

        assert expected
        assert expected <= CYCLING_RELEVANT_WARNING_CODES

    def test_the_kinds_left_out_on_purpose_stay_out(self):
        """路面凍結系（霜・着氷・着雪・なだれ・低温）と濃霧は、警告としての出し方が他と
        違うため別扱いにしてある。高潮・乾燥・その他の注意報は道路走行への関連が薄い。
        ここへ足すと、走行に関係のないバッジが常時並ぶ。
        """
        for code in ("20", "21", "22", "23", "24", "25", "26", "27", "08", "19", "38", "48"):
            assert code not in CYCLING_RELEVANT_WARNING_CODES, code


class TestExtractActiveWarnings:
    """1地域ぶんの電文から、いま出ていて走行に関わるものだけを取り出す。"""

    @staticmethod
    def _kind(code: str | None = "14", status: str = "発表", **extra) -> dict:
        kind = {"status": status, **extra}
        if code is not None:
            kind["code"] = code
        return kind

    def test_an_issued_warning_is_returned_with_its_name_and_level(self):
        [warning] = extract_active_warnings([self._kind("03")])

        assert warning.code == "03"
        assert warning.name == WARNING_CODE_NAMES["03"]
        assert warning.level == warning_level("03")

    def test_a_continued_warning_is_still_active(self):
        assert extract_active_warnings([self._kind("03", status="継続")])

    def test_a_released_warning_is_not_active(self):
        """直前まで出ていたが取り下げられたもの。出し続けると、止んだ雨の警報が残る。"""
        assert extract_active_warnings([self._kind("03", status="解除")]) == []

    def test_an_area_with_nothing_issued_has_no_code(self):
        """何も出ていない地域の要素は`code`キー自体を持たない。KeyErrorにせず飛ばす。"""
        assert extract_active_warnings([{"status": "発表警報・注意報はなし"}]) == []

    def test_a_kind_unrelated_to_cycling_is_dropped(self):
        assert extract_active_warnings([self._kind("21")]) == []

    def test_the_additions_are_carried_through(self):
        [warning] = extract_active_warnings([self._kind("03", additions=["浸水害"])])

        assert warning.additions == ["浸水害"]

    def test_a_kind_without_additions_gets_an_empty_list(self):
        """Noneで返すと、読む側がその都度Noneを見る必要が出る。"""
        [warning] = extract_active_warnings([self._kind("03")])

        assert warning.additions == []

    def test_several_kinds_are_all_returned(self):
        kinds = [self._kind("03"), self._kind("21"), self._kind("14"), self._kind("04", status="解除")]

        assert [w.code for w in extract_active_warnings(kinds)] == ["03", "14"]

    def test_no_kinds_at_all_gives_nothing(self):
        assert extract_active_warnings([]) == []


def test_only_issued_or_continued_counts_as_active():
    """この2語以外を通すと、解除済み・未発表のものが現在の警報として出る。"""
    assert ACTIVE_STATUSES == frozenset({"発表", "継続"})
