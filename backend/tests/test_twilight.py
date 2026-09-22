"""`domain/twilight.py`——市民薄明にもとづく夜間判定と、日の出・日没の表示値。"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain.route import Coordinates
from app.domain.time_zone import JST
from app.domain.twilight import is_night, sunrise_sunset_jst

# 下の暦との突き合わせは、この座標に対する公開値を使う。動かすと期待値が合わなくなる。
TOKYO = Coordinates(latitude=35.6762, longitude=139.6503)
# 白夜・極夜が起きる緯度。市民薄明が定義できない日がある。
SVALBARD = Coordinates(latitude=78.22, longitude=15.63)

MIDSUMMER = date(2026, 6, 21)
MIDWINTER = date(2026, 12, 21)


def _jst(on_date: date, hour: int, minute: int = 0) -> datetime:
    return datetime(on_date.year, on_date.month, on_date.day, hour, minute, tzinfo=JST)


class TestIsNight:
    def test_midday_is_not_night(self):
        assert is_night(TOKYO, _jst(MIDSUMMER, 12)) is False

    def test_the_small_hours_are_night(self):
        assert is_night(TOKYO, _jst(MIDSUMMER, 1)) is True

    def test_sunset_itself_is_not_yet_night(self):
        """境界は日の入りではなく**市民薄明の終わり**。日没直後はまだ屋外の視認性が残る。
        日の入りを境界にすると、まだ明るい時間帯に街灯の軸が効き始める。
        """
        _, sunset = sunrise_sunset_jst(TOKYO, MIDSUMMER)
        at_sunset = datetime.fromisoformat(sunset)

        assert is_night(TOKYO, at_sunset) is False
        assert is_night(TOKYO, at_sunset + timedelta(hours=2)) is True

    def test_a_naive_time_is_read_as_utc(self):
        """呼び出し元の到達時刻計算はUTCで統一されている。現地時刻と取り違えると、
        9時間ずれた判定になる。
        """
        aware = _jst(MIDSUMMER, 12)
        naive = aware.astimezone(timezone.utc).replace(tzinfo=None)

        assert is_night(TOKYO, naive) == is_night(TOKYO, aware)

    def test_the_judgement_holds_across_the_utc_date_boundary(self):
        """日本の現地日とUTCの暦日はずれる。`astral`は「そのUTC暦日に収まるイベント」を
        返すため、同じ引数から返るdawnとduskが別の現地日を指し、単純な範囲比較では
        昼夜が入れ替わる。現地の深夜0時台と正午は、UTCでは前日と当日に分かれる。
        """
        assert is_night(TOKYO, _jst(MIDSUMMER, 0, 30)) is True
        assert is_night(TOKYO, _jst(MIDSUMMER, 12)) is False

    def test_every_hour_of_a_day_is_decided_consistently(self):
        """1日を通すと、夜→昼→夜の順に1度ずつ切り替わる。日付跨ぎの取り違えがあると
        途中で余分に反転する。
        """
        flags = [is_night(TOKYO, _jst(MIDSUMMER, hour)) for hour in range(24)]
        switches = sum(1 for a, b in zip(flags, flags[1:]) if a != b)

        assert flags[0] is True
        assert switches == 2

    def test_the_first_days_of_a_polar_day_are_not_treated_as_night(self):
        """白夜が始まった直後は、窓の中に`at`より後のイベントが無く、数日前の夕暮れだけが
        残る。それを引きずると、太陽が沈まない期間を夜と判定する。
        """
        # この地点ではこの日から白夜に入り、窓（前後2日）で定義できるのは2日前だけになる。
        assert is_night(SVALBARD, datetime(2026, 4, 5, 12, tzinfo=timezone.utc)) is False

    def test_a_polar_day_is_not_treated_as_night(self):
        """市民薄明が定義できない緯度では夜にしない。街灯の軸を一日中効かせるより、
        効かせない方が安全側。
        """
        assert is_night(SVALBARD, _jst(MIDSUMMER, 12)) is False
        assert is_night(SVALBARD, _jst(MIDSUMMER, 0)) is False


class TestIsNightAgainstAPublishedAlmanac:
    """`astral`の計算を、独立した公開値と突き合わせる。

    sunrise-sunset.org（NOAA準拠）が返す東京の市民薄明終了（civil_twilight_end）と比べる。
    astralとNOAAは太陽視差・大気差の扱いがわずかに違うため、境界±3分は許容差として扱う
    ——`is_night`は走行中の照明の要否という粗い判定で、境界前後の数分を厳密に分ける用途
    ではない。夏至・冬至・秋分の3点で、季節の違う薄明パターンを見る。
    """

    @pytest.mark.parametrize(
        "civil_twilight_end",
        [
            datetime(2024, 6, 21, 19, 30, 35, tzinfo=JST),
            datetime(2024, 12, 21, 17, 0, 8, tzinfo=JST),
            datetime(2024, 9, 23, 18, 2, 37, tzinfo=JST),
        ],
    )
    def test_the_boundary_sits_within_three_minutes_of_the_published_time(self, civil_twilight_end):
        assert is_night(TOKYO, civil_twilight_end - timedelta(minutes=3)) is False
        assert is_night(TOKYO, civil_twilight_end + timedelta(minutes=3)) is True


def test_the_judgement_also_holds_in_the_southern_hemisphere_far_east():
    """日付跨ぎの罠は経度が東であるほど効く。南半球（薄明の並びが逆の季節）かつUTC+12で
    確かめる。
    """
    wellington = Coordinates(latitude=-41.2865, longitude=174.7762)
    nzst = timezone(timedelta(hours=12))

    assert is_night(wellington, datetime(2024, 6, 21, 0, 30, tzinfo=nzst)) is True
    assert is_night(wellington, datetime(2024, 6, 21, 12, 0, tzinfo=nzst)) is False


class TestSunriseSunsetJst:
    def test_times_are_returned_in_jst(self):
        sunrise, sunset = sunrise_sunset_jst(TOKYO, MIDSUMMER)

        assert datetime.fromisoformat(sunrise).utcoffset() == timedelta(hours=9)
        assert datetime.fromisoformat(sunset).utcoffset() == timedelta(hours=9)

    def test_times_fall_on_the_requested_local_date(self):
        sunrise, sunset = sunrise_sunset_jst(TOKYO, MIDSUMMER)

        assert datetime.fromisoformat(sunrise).date() == MIDSUMMER
        assert datetime.fromisoformat(sunset).date() == MIDSUMMER

    def test_sunrise_comes_before_sunset(self):
        sunrise, sunset = sunrise_sunset_jst(TOKYO, MIDSUMMER)

        assert datetime.fromisoformat(sunrise) < datetime.fromisoformat(sunset)

    def test_winter_days_are_shorter_than_summer_days(self):
        def length(on_date: date) -> timedelta:
            sunrise, sunset = sunrise_sunset_jst(TOKYO, on_date)
            return datetime.fromisoformat(sunset) - datetime.fromisoformat(sunrise)

        assert length(MIDWINTER) < length(MIDSUMMER)

    def test_a_latitude_without_a_sunrise_returns_nothing(self):
        """定義できない日を既定値で埋めない——「日の出0時」として表示される。"""
        assert sunrise_sunset_jst(SVALBARD, MIDSUMMER) == (None, None)
