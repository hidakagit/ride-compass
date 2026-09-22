"""`domain/jma_warning.py`——気象庁の警報コードを、走行に関わるものだけへ絞る。

電文の取得・地域の解決は`test_weather_route.py`・`test_jma_area.py`が持つ。
コード表そのものは書き写さず、全件に対して成り立つことだけを見る。
"""

from app.domain.jma_warning import (
    WARNING_CODE_NAMES,
    extract_active_warnings,
    warning_level,
)


class TestWarningLevel:
    """コードからバッジの段を決める。

    実装は名称に「特別警報」「警報」が含まれるかで決めているが、**その規則をここで
    書き写して突き合わせない**（恒真になる）。代表的なコードが意味どおりの段へ落ちること
    と、全件が3段のいずれかへ落ちることを見る。
    """

    def test_representative_codes_land_where_their_meaning_says(self):
        assert warning_level("33") == "emergency_warning"  # 大雨特別警報
        assert warning_level("03") == "warning"  # 大雨警報
        assert warning_level("10") == "advisory"  # 大雨注意報

    def test_the_same_hazard_gets_heavier_as_the_bulletin_escalates(self):
        """注意報→警報→特別警報は同じ現象の段。逆転や同一視をすると、バッジの色が
        強さを表さなくなる。
        """
        order = ["advisory", "warning", "emergency_warning"]

        assert order.index(warning_level("10")) < order.index(warning_level("03"))
        assert order.index(warning_level("03")) < order.index(warning_level("33"))

    def test_an_unknown_code_falls_to_the_lightest(self):
        """知らないコードで赤いバッジを出さない。電文が増えても表示が壊れない側へ倒す。"""
        assert warning_level("99") == "advisory"


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
