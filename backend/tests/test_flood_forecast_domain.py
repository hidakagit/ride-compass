"""`domain/flood_forecast.py`——指定河川洪水予報の電文1件を、出発地点の氾濫警戒へ変える。

電文の取得は`test_flood_client.py`、訓練電文の除外と複数河川のまとめ上げは
`test_flood_service.py`、地域コードの解決は`test_jma_area.py`が持つ。

対応表の典拠は実装が持つ。ここでは表を書き写さず、代表コードの意味と全件に対して
成り立つことだけを見る。
"""

import pytest

from app.domain.flood_forecast import CLEARED_CODE, extract_active_flood_forecast

CLASS20 = "1310100"
CLASS10 = "130010"


def _entry(code: str | None = "30", **overrides) -> dict:
    entry: dict = {
        "item": {"code": code, "condition": "氾濫危険水位に到達"} if code is not None else {},
        "class20Codes": [CLASS20],
        "class10Codes": [CLASS10],
        "riverCode": "8306050001",
        "riverName": "荒川",
        "reportDatetime": "2026-09-22T05:00:00+09:00",
    }
    entry.update(overrides)
    return entry


class TestWhetherAnythingIsReturned:
    """この電文が、この地点の、いま出ている予報かを決める。"""

    def test_the_cleared_code_means_nothing_is_active(self):
        """`status`と同じ発想で読むと、解除済みの河川が出続ける。"""
        assert extract_active_flood_forecast(_entry(CLEARED_CODE), CLASS20, CLASS10) is None

    def test_a_downgrade_to_this_level_is_still_active(self):
        """コード"22"は「上位の警報が解除されて当レベルへ引き下がった」。文字面の「解除」に
        引きずられて落とすと、氾濫注意報が続いている河川が画面から消える。
        """
        assert extract_active_flood_forecast(_entry("22"), CLASS20, CLASS10) is not None

    def test_an_unknown_code_is_dropped(self):
        """レベルを決められないコードで何かを出すと、段の無いバッジになる。"""
        assert extract_active_flood_forecast(_entry("99"), CLASS20, CLASS10) is None

    def test_an_entry_without_an_item_is_dropped(self):
        assert extract_active_flood_forecast({"class20Codes": [CLASS20]}, CLASS20, CLASS10) is None

    def test_an_item_without_a_code_is_dropped(self):
        assert extract_active_flood_forecast(_entry(None), CLASS20, CLASS10) is None


class TestWhetherThePointIsCovered:
    """電文は河川ごとに届き、流域の市区町村を列挙している。出発地点がその中に無ければ
    他人事の予報になる。
    """

    def test_a_match_on_the_municipality_is_enough(self):
        entry = _entry(class10Codes=["999999"])

        assert extract_active_flood_forecast(entry, CLASS20, CLASS10) is not None

    def test_a_match_on_the_broader_area_is_enough(self):
        """電文がclass20（市区町村）まで下ろしていない場合がある。class10だけで諦めると、
        その河川の予報を誰も受け取れない。
        """
        entry = _entry(class20Codes=["9999999"])

        assert extract_active_flood_forecast(entry, CLASS20, CLASS10) is not None

    def test_a_point_in_neither_list_is_dropped(self):
        entry = _entry(class20Codes=["9999999"], class10Codes=["999999"])

        assert extract_active_flood_forecast(entry, CLASS20, CLASS10) is None

    def test_missing_area_lists_are_treated_as_empty(self):
        """キーごと欠けた電文でTypeErrorにすると、1件の欠落が全河川の取得を落とす。"""
        entry = _entry()
        del entry["class20Codes"]
        del entry["class10Codes"]

        assert extract_active_flood_forecast(entry, CLASS20, CLASS10) is None


class TestTheBadgeContents:
    def test_the_label_names_the_river_and_the_level(self):
        forecast = extract_active_flood_forecast(_entry("40"), CLASS20, CLASS10)

        assert forecast.label == "荒川氾濫危険警報"

    def test_the_bulletin_fields_are_carried_through(self):
        forecast = extract_active_flood_forecast(_entry(), CLASS20, CLASS10)

        assert forecast.river_code == "8306050001"
        assert forecast.river_name == "荒川"
        assert forecast.condition == "氾濫危険水位に到達"
        assert forecast.report_datetime == "2026-09-22T05:00:00+09:00"

    def test_missing_optional_fields_become_empty_strings(self):
        """Noneを入れるとモデルが弾き、1件の欠落で全河川が落ちる。表示側は空文字を
        そのまま書ける。
        """
        entry = _entry()
        for key in ("riverCode", "riverName", "reportDatetime"):
            del entry[key]
        entry["item"] = {"code": "30"}

        forecast = extract_active_flood_forecast(entry, CLASS20, CLASS10)

        assert (forecast.river_code, forecast.river_name, forecast.condition) == ("", "", "")
        assert forecast.report_datetime == ""

    def test_a_null_river_name_does_not_leak_into_the_label(self):
        """JSONのnullをそのまま繋ぐと「None氾濫警報」が画面に出る。"""
        forecast = extract_active_flood_forecast(_entry(riverName=None), CLASS20, CLASS10)

        assert forecast.label == "氾濫警報"


class TestTheLevelScale:
    """レベルは気象庁の5段階警戒レベルに揃えてある（氾濫予報は2〜5のみ）。"""

    @pytest.mark.parametrize(
        ("code", "level", "suffix"),
        [
            ("20", 2, "氾濫注意報"),
            ("30", 3, "氾濫警報"),
            ("40", 4, "氾濫危険警報"),
            ("51", 5, "氾濫特別警報"),
        ],
    )
    def test_the_representative_codes_land_on_the_level_their_bulletin_means(self, code, level, suffix):
        forecast = extract_active_flood_forecast(_entry(code), CLASS20, CLASS10)

        assert forecast.level == level
        assert forecast.label.endswith(suffix)

    def test_the_badge_gets_heavier_as_the_level_rises(self):
        """段が逆転・同一視されると、バッジの色が危なさを表さなくなる。"""
        order = ["advisory", "warning", "severe_warning", "emergency_warning"]
        badges = [
            extract_active_flood_forecast(_entry(code), CLASS20, CLASS10).badge_level
            for code in ("20", "30", "40", "51")
        ]

        assert [order.index(b) for b in badges] == sorted(order.index(b) for b in badges)
        assert len(set(badges)) == 4
