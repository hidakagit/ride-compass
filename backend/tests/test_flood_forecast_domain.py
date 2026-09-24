"""`domain/flood_forecast.py`——指定河川洪水予報の電文1件から、出発地点に該当する現在の氾濫予報を取り出す。

ここで見ないもの:
- 電文の取得と地点のコード解決 → `services/flood_service.py`（`test_weather_route.py`等）
- 段階の色・呼び名の画面への配り方 → `domain/warning_display.py`

期待値の段・呼び名はコードの表（`FLOOD_CODE_LEVELS`）から引き、数字を書き写さない。例外は代表コードの段で、
これは表そのものが正しいかを気象庁の電文フォーマット（表２）と5段階の警戒レベルに突き合わせる。
"""

from typing import get_args

import pytest

from app.domain import flood_forecast

ACTIVE_CODE = next(iter(flood_forecast.FLOOD_CODE_LEVELS))


def _entry(code: str | None = ACTIVE_CODE, **overrides) -> dict:
    entry = {
        "item": {} if code is None else {"code": code, "condition": "氾濫注意水位に到達"},
        "class20Codes": ["1310100"],
        "class10Codes": ["130010"],
        "riverCode": "8301",
        "riverName": "多摩川",
        "reportDatetime": "2026-09-24T10:00:00+09:00",
    }
    entry.update(overrides)
    return entry


# ---- 段の宣言（表全体に対する不変条件） ----


def test_every_level_in_the_code_table_has_its_display_name():
    levels = set(flood_forecast.FLOOD_CODE_LEVELS.values())
    assert levels, "コードの表が空"

    for level in levels:
        assert flood_forecast.FLOOD_LEVEL_LABELS[level.badge_level] == level.suffix


def test_a_higher_flood_level_never_shows_a_lighter_badge():
    order = get_args(flood_forecast.WarningBadgeLevel)
    levels = sorted(set(flood_forecast.FLOOD_CODE_LEVELS.values()), key=lambda lv: lv.level)

    badge_ranks = [order.index(lv.badge_level) for lv in levels]
    assert badge_ranks == sorted(badge_ranks)
    assert len(set(badge_ranks)) == len(badge_ranks)


@pytest.mark.parametrize(
    ("code", "level", "suffix"),
    [
        ("20", 2, "氾濫注意報"),
        ("30", 3, "氾濫警報"),
        ("40", 4, "氾濫危険警報"),
        ("51", 5, "氾濫特別警報"),
    ],
)
def test_the_representative_codes_land_on_the_level_their_bulletin_means(code, level, suffix):
    # 気象庁「指定河川洪水予報」電文の表２と、5段階の警戒レベル
    assert (flood_forecast.FLOOD_CODE_LEVELS[code].level, flood_forecast.FLOOD_CODE_LEVELS[code].suffix) == (
        level,
        suffix,
    )


# ---- 電文1件の読み取り ----


@pytest.mark.parametrize("code", sorted(flood_forecast.FLOOD_CODE_LEVELS))
def test_an_active_code_for_the_starting_area_becomes_a_forecast(code):
    level = flood_forecast.FLOOD_CODE_LEVELS[code]

    forecast = flood_forecast.extract_active_flood_forecast(_entry(code), "1310100", "130010")

    assert forecast == flood_forecast.ActiveFloodForecast(
        river_code="8301",
        river_name="多摩川",
        level=level.level,
        badge_level=level.badge_level,
        label=f"多摩川{level.suffix}",
        condition="氾濫注意水位に到達",
        report_datetime="2026-09-24T10:00:00+09:00",
    )


@pytest.mark.parametrize("code", [None, "10", "no_such_code"])
def test_no_code_or_a_code_that_is_not_active_gives_nothing(code):
    # "10"は完全解除（表に載せない）。表に無いコードは現在アクティブな状態を表さない
    assert code not in flood_forecast.FLOOD_CODE_LEVELS
    assert flood_forecast.extract_active_flood_forecast(_entry(code), "1310100", "130010") is None


def test_an_entry_without_an_item_gives_nothing():
    entry = _entry()
    del entry["item"]

    assert flood_forecast.extract_active_flood_forecast(entry, "1310100", "130010") is None


@pytest.mark.parametrize(
    ("class20", "class10"),
    [
        ("1310100", "999999"),  # 市区町村の区域で当たる
        ("9999999", "130010"),  # 二次細分区域でだけ当たる
    ],
)
def test_the_starting_area_matches_by_either_area_code(class20, class10):
    assert flood_forecast.extract_active_flood_forecast(_entry(), class20, class10) is not None


def test_an_entry_for_another_area_gives_nothing():
    assert flood_forecast.extract_active_flood_forecast(_entry(), "9999999", "999999") is None


def test_an_entry_without_area_lists_matches_nothing():
    entry = _entry()
    del entry["class20Codes"]
    del entry["class10Codes"]

    assert flood_forecast.extract_active_flood_forecast(entry, "1310100", "130010") is None


def test_missing_texts_become_empty_and_the_label_is_the_level_name_alone():
    entry = {"item": {"code": ACTIVE_CODE}, "class20Codes": ["1310100"]}

    forecast = flood_forecast.extract_active_flood_forecast(entry, "1310100", "130010")

    assert (forecast.river_code, forecast.river_name, forecast.condition, forecast.report_datetime) == ("", "", "", "")
    assert forecast.label == flood_forecast.FLOOD_CODE_LEVELS[ACTIVE_CODE].suffix


def test_null_texts_become_empty_too():
    entry = _entry(riverCode=None, riverName=None, reportDatetime=None)
    entry["item"]["condition"] = None

    forecast = flood_forecast.extract_active_flood_forecast(entry, "1310100", "130010")

    assert (forecast.river_code, forecast.river_name, forecast.condition, forecast.report_datetime) == ("", "", "", "")
    assert forecast.label == flood_forecast.FLOOD_CODE_LEVELS[ACTIVE_CODE].suffix
