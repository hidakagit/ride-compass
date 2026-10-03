"""`domain/twilight.py`——夜かどうか（市民薄明の外か）と、その日の日の出・日没。

入口は`is_night`（夜の軸を効かせるか）と`sunrise_sunset_jst`（観測の表示に添える時刻）。

「夜」の定義は太陽の高度が−6度より下（市民薄明の終わり）。期待値は、`astral`の太陽高度
（`astral.sun.elevation`）という、実装が使う薄明の時刻とは別の道で求める。日の出・日没は
国立天文台の暦と比べる。

ここで見ないもの:
- 夜の軸の重みを切り替えること（`domain/axis_definitions.py: time_scoped_weights`） → `test_axis_hierarchy.py`
- 観測の応答へ日の出・日没を埋めること → `test_jma_amedas_service.py`・`test_amedas_route.py`
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from astral import Observer
from astral.sun import elevation
from hypothesis import assume, given
from hypothesis import strategies as st

from app.domain.route import Coordinates
from app.domain.twilight import is_night, sunrise_sunset_jst

JST = timezone(timedelta(hours=9))
TOKYO = Coordinates(latitude=35.6581, longitude=139.7414)

#: 本番の範囲（日本の陸地の緯度・経度）。
PLACES = st.builds(Coordinates, latitude=st.floats(24.0, 45.5), longitude=st.floats(122.9, 146.0))
MOMENTS = st.datetimes(min_value=datetime(2026, 1, 1), max_value=datetime(2027, 12, 31)).map(
    lambda at: at.replace(tzinfo=timezone.utc)
)


@given(PLACES, MOMENTS)
def test_night_is_when_the_sun_is_lower_than_six_degrees_below_the_horizon(place, at):
    """日付の境をまたぐ時刻（東経では日暮れと夜明けがUTCの暦日の中で入れ替わる）も含めて、一日中で成り立つ。"""
    altitude = elevation(Observer(latitude=place.latitude, longitude=place.longitude), at)
    assume(abs(altitude + 6.0) > 0.3)  # 境の前後1分ほどは、計算の細部で入れ替わりうる

    assert is_night(place, at) is (altitude < -6.0)


def test_a_naive_time_is_read_as_utc():
    """到達時刻の計算はUTCで揃っている。3時はUTCなら東京の正午、JSTなら夜。"""
    naive = datetime(2026, 7, 1, 3, 0)

    assert is_night(TOKYO, naive) is False
    assert is_night(TOKYO, naive.replace(tzinfo=JST)) is True


@pytest.mark.parametrize(
    ("place", "at"),
    [
        (Coordinates(latitude=89.0, longitude=0.0), datetime(2026, 12, 21, 0, 0, tzinfo=timezone.utc)),
        (Coordinates(latitude=89.0, longitude=0.0), datetime(2026, 6, 21, 0, 0, tzinfo=timezone.utc)),
        # 白夜に入る境目。最後の薄明の出来事は日暮れで、次の夜明けを前後数日の中に挟めない。
        (Coordinates(latitude=66.0, longitude=0.0), datetime(2026, 5, 11, 0, 0, tzinfo=timezone.utc)),
    ],
    ids=["極夜", "白夜", "白夜に入る境目"],
)
def test_where_civil_twilight_cannot_be_drawn_it_is_not_treated_as_night(place, at):
    assert is_night(place, at) is False


def test_tokyo_sunrise_and_sunset_match_the_national_almanac():
    """国立天文台の暦（東京、2026年6月21日）: 日の出 4:25・日の入り 19:00（分の表記なので±1分）。"""
    twilight = sunrise_sunset_jst(TOKYO, date(2026, 6, 21))
    assert twilight is not None

    sunrise = datetime.fromisoformat(twilight.sunrise)
    sunset = datetime.fromisoformat(twilight.sunset)

    assert sunrise.utcoffset() == sunset.utcoffset() == timedelta(hours=9)
    assert abs(sunrise - datetime(2026, 6, 21, 4, 25, 30, tzinfo=JST)) <= timedelta(minutes=1)
    assert abs(sunset - datetime(2026, 6, 21, 19, 0, 30, tzinfo=JST)) <= timedelta(minutes=1)


@given(PLACES, st.dates(min_value=date(2026, 1, 1), max_value=date(2027, 12, 31)))
def test_sunrise_and_sunset_fall_on_the_asked_japanese_day_in_daylight(place, on_date):
    """日本の暦日の日の出・日没で、その間は夜ではない（日没から市民薄明の終わりまでは、まだ明るい）。"""
    twilight = sunrise_sunset_jst(place, on_date)
    assert twilight is not None
    sunrise = datetime.fromisoformat(twilight.sunrise)
    sunset = datetime.fromisoformat(twilight.sunset)

    assert sunrise.date() == sunset.date() == on_date
    assert sunrise < sunset
    assert not is_night(place, sunrise)
    assert not is_night(place, sunset)


def test_there_is_no_sunrise_or_sunset_in_the_polar_day():
    assert sunrise_sunset_jst(Coordinates(latitude=89.0, longitude=0.0), date(2026, 6, 21)) is None
