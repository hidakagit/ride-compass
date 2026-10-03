"""`domain/flood_forecast.py`——指定河川洪水予報の電文1件から、出発地点にかかる発表中の予報を取り出す。

入口は`extract_active_flood_forecast`。取り出しは、コード対応表`FLOOD_CODE_LEVELS`（配信元の資料の写し。本番の正本を
持つ宣言のデータ）の中身に踏み込まず、架空のコードを足して確かめる。表の段そのものの不変条件（段が上がるほどバッジが
重い）だけは、差し替えずに本物の表で見る。

ここで見ないもの:
- 電文の形を`FloodBulletin`へ解くこと → `test_flood_client.py`
- 地点から区域を引くこと・電文を集めて並べること → `test_flood_service.py`
- 段階ごとの呼び名`FLOOD_LEVEL_LABELS`——段の宣言から導き、全段がそろっていることは
  `domain/warning_display.py`がimportの時点で全段を引いて確かめる
"""

from typing import get_args

import pytest

from app.domain import flood_forecast
from app.domain.flood_forecast import FloodBulletin, FloodLevel, extract_active_flood_forecast

ACTIVE = "t_active"


def test_a_higher_flood_level_always_shows_a_heavier_badge():
    """段とバッジは別々に宣言している。軽いバッジが重い段に付くと、危険な氾濫を軽く見せる。"""
    badge_order = get_args(flood_forecast.WarningBadgeLevel)
    levels = sorted(set(flood_forecast.FLOOD_CODE_LEVELS.values()), key=lambda flood: flood.level)

    ranks = [badge_order.index(flood.badge_level) for flood in levels]
    assert len(levels) > 1
    assert all(lighter < heavier for lighter, heavier in zip(ranks, ranks[1:]))


@pytest.fixture
def _codes(monkeypatch):
    monkeypatch.setitem(flood_forecast.FLOOD_CODE_LEVELS, ACTIVE, FloodLevel(3, "warning", "架空の段"))


def _bulletin(code: str | None, class20_codes=("1310100",), class10_codes=("130010",)) -> FloodBulletin:
    return FloodBulletin(
        code=code,
        class20_codes=tuple(class20_codes),
        class10_codes=tuple(class10_codes),
        river_code="850000",
        river_name="架空川",
        condition="氾濫のおそれ",
        report_datetime="2026-07-01T10:00:00+09:00",
    )


@pytest.mark.usefixtures("_codes")
def test_an_active_code_over_the_start_area_becomes_a_forecast_named_after_the_river():
    forecast = extract_active_flood_forecast(_bulletin(ACTIVE), "1310100", "130010")

    assert forecast is not None
    assert forecast.model_dump() == {
        "river_code": "850000",
        "river_name": "架空川",
        "level": 3,
        "badge_level": "warning",
        "label": "架空川架空の段",
        "condition": "氾濫のおそれ",
        "report_datetime": "2026-07-01T10:00:00+09:00",
    }


@pytest.mark.usefixtures("_codes")
@pytest.mark.parametrize("code", [None, "t_not_in_the_table"])
def test_a_bulletin_whose_code_is_not_an_active_state_gives_nothing(code):
    """表に無いコード（完全解除など）とコードの無い電文は、発表中ではない。"""
    assert extract_active_flood_forecast(_bulletin(code), "1310100", "130010") is None


@pytest.mark.usefixtures("_codes")
@pytest.mark.parametrize(
    ("class20_codes", "class10_codes", "applies"),
    [
        (("1310100",), (), True),
        ((), ("130010",), True),
        (("1310200",), ("130020",), False),
    ],
)
def test_the_forecast_applies_when_either_the_area_or_its_subdivision_is_covered(class20_codes, class10_codes, applies):
    bulletin = _bulletin(ACTIVE, class20_codes=class20_codes, class10_codes=class10_codes)
    assert (extract_active_flood_forecast(bulletin, "1310100", "130010") is not None) is applies
