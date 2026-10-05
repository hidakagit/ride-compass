"""`domain/flood_forecast.py`——指定河川洪水予報の電文1件から、出発地点にかかる発表中の予報を取り出す。

入口は`extract_active_flood_forecast`。コード対応表`FLOOD_CODE_LEVELS`（配信元の資料の写し）は差し替えず、本物の表の
行から電文を組み立てる——どのコードがどの段かには踏み込まない。

ここで見ないもの:
- 電文の形を`FloodBulletin`へ解くこと → `test_flood_client.py`
- 地点から区域を引くこと・電文を集めて並べること → `test_flood_service.py`
- 段階ごとの呼び名`FLOOD_LEVEL_LABELS`——段の宣言から導き、全段がそろっていることは
  `domain/warning_display.py`がimportの時点で全段を引いて確かめる
"""

import pytest

from app.domain import flood_forecast
from app.domain.flood_forecast import FloodBulletin, extract_active_flood_forecast

ACTIVE, ACTIVE_LEVEL = next(iter(flood_forecast.FLOOD_CODE_LEVELS.items()))


def _bulletin(code: str | None, class20_codes=("1310100",), class10_codes=("130010",)) -> FloodBulletin:
    return FloodBulletin(
        code=code,
        class20_codes=tuple(class20_codes),
        class10_codes=tuple(class10_codes),
        river_code="850000",
        river_name="架空川",
        condition="氾濫のおそれ",
    )


def test_an_active_code_over_the_start_area_becomes_a_forecast_named_after_the_river():
    forecast = extract_active_flood_forecast(_bulletin(ACTIVE), "1310100", "130010")

    assert forecast is not None
    assert forecast.model_dump() == {
        "river_code": "850000",
        "badge_level": ACTIVE_LEVEL.badge_level,
        "label": f"架空川{ACTIVE_LEVEL.suffix}",
        "condition": "氾濫のおそれ",
    }


@pytest.mark.parametrize("code", [None, "t_not_in_the_table"])
def test_a_bulletin_whose_code_is_not_an_active_state_gives_nothing(code):
    """表に無いコード（完全解除など）とコードの無い電文は、発表中ではない。"""
    assert extract_active_flood_forecast(_bulletin(code), "1310100", "130010") is None


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
