from datetime import datetime, timedelta, timezone

import pytest

from app.domain.route import Coordinates
from app.domain.twilight import is_night

TOKYO = Coordinates(latitude=35.6762, longitude=139.6503)


class TestIsNightAgainstKnownAlmanac:
    """sunrise-sunset.org（NOAA準拠の公開API、2026-08-20に実測取得）の東京・市民薄明終了
    （civil_twilight_end）時刻との突き合わせ。astralとNOAAは太陽視差・大気差の扱いが
    わずかに異なるため、境界±3分は許容誤差として扱う（is_night自体は「境界の前後数分」を
    厳密に区別する用途ではなく、走行中の照明の要否という粗い判定のため）。

    夏至（2024-06-21, civil_twilight_end=19:30:35 JST）・冬至（2024-12-21, 17:00:08 JST）・
    秋分（2024-09-23, 18:02:37 JST）の3点で季節の異なる薄明パターンを網羅する。
    """

    @pytest.mark.parametrize(
        ("dusk_jst", "before_offset_min", "after_offset_min"),
        [
            (datetime(2024, 6, 21, 19, 30, 35, tzinfo=timezone(timedelta(hours=9))), -3, 3),
            (datetime(2024, 12, 21, 17, 0, 8, tzinfo=timezone(timedelta(hours=9))), -3, 3),
            (datetime(2024, 9, 23, 18, 2, 37, tzinfo=timezone(timedelta(hours=9))), -3, 3),
        ],
    )
    def test_dusk_boundary_matches_known_civil_twilight_end(self, dusk_jst, before_offset_min, after_offset_min):
        before = dusk_jst + timedelta(minutes=before_offset_min)
        after = dusk_jst + timedelta(minutes=after_offset_min)
        assert is_night(TOKYO, before) is False
        assert is_night(TOKYO, after) is True


def test_is_night_true_for_deep_night():
    # 2024-06-21 02:00 JST（真夜中）
    at = datetime(2024, 6, 21, 2, 0, tzinfo=timezone(timedelta(hours=9)))
    assert is_night(TOKYO, at) is True


def test_is_night_false_for_noon():
    at = datetime(2024, 6, 21, 12, 0, tzinfo=timezone(timedelta(hours=9)))
    assert is_night(TOKYO, at) is False


def test_is_night_accepts_naive_datetime_as_utc():
    # tz-naiveはUTCとみなす（呼び出し元の到達時刻計算がUTCで統一されているため）。
    # 2024-06-21T03:00Z = JST 12:00（昼）
    at_naive = datetime(2024, 6, 21, 3, 0)
    assert is_night(TOKYO, at_naive) is False


def test_is_night_handles_dateline_crossing_longitude():
    # 経度が東側で日付境界をまたぐケース（実装のdocstring参照: 同じdate引数から
    # 返るdawn/duskが別々の現地日を指す罠）を東京以外の地点でも確認する。
    wellington = Coordinates(latitude=-41.2865, longitude=174.7762)
    # 深夜帯（現地の真夜中付近）は夜と判定されるはず。
    midnight_local = datetime(2024, 6, 21, 0, 30, tzinfo=timezone(timedelta(hours=12)))
    assert is_night(wellington, midnight_local) is True
    noon_local = datetime(2024, 6, 21, 12, 0, tzinfo=timezone(timedelta(hours=12)))
    assert is_night(wellington, noon_local) is False
