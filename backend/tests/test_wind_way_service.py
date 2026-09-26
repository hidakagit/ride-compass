"""鍵→wind_drag_ratio配信層（`services/wind_way_service.py`）。ルートを出す前の地図の風。

走行方位は呼び出し側が指定する単一の値で、道路自身の向きは使わない。予報の地点と時刻は
ルートの区間と同じ選び方——各道は中ほどに最も近い予報の格子点（緯度0.05度・経度0.0625度の
固定の格子）の、指定時刻に最も近い時刻の風を引く。予報の範囲の外の時刻は塗らない。

差し替えるのはDB（リポジトリ）とMSMのローカルファイルの読み出しだけで、天候サービス・
評価器は本物を通す。
"""

import inspect
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.domain.msm import wind_speed_and_direction
from app.domain.time_zone import JST
from app.domain.wind import kmh_to_ms, wind_drag_ratio
from app.infrastructure import msm_client
from app.infrastructure.msm_client import MsmUnavailableError
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.weather_service import WeatherService
from app.services.wind_way_service import WindWayService

# 東京駅付近のz14タイル（緯度35.67〜35.69・経度139.71〜139.74あたり）
Z, X, Y = 14, 14551, 6447
SPEED_KMH = 20.0
AT = datetime(2026, 8, 30, 9, 0)
TIMES = ["2026-08-30T08:00", "2026-08-30T09:00", "2026-08-30T10:00"]


class FakeMidpointsRepository:
    """RoadGraphRepositoryのうちget_feature_midpoints_in_tileだけを実装したフェイク。

    引数は本物の定義へ当てて照合する。フェイクが自前の引数を持つと、本物の引数が変わっても
    呼び出し側の食い違いを通してしまう。
    """

    def __init__(self, midpoints: dict[str, tuple[float, float]] | None, error: Exception | None = None):
        self._midpoints = midpoints
        self._error = error
        self.calls: list[tuple] = []

    async def get_feature_midpoints_in_tile(self, *args, **kwargs):
        inspect.signature(RoadGraphRepository.get_feature_midpoints_in_tile).bind(self, *args, **kwargs)
        self.calls.append(args)
        if self._error is not None:
            raise self._error
        return self._midpoints


def _wind_uv(latitudes, longitudes, hour_index):
    """地点と時刻ごとに違う風（東西・南北成分）。どの格子点・時刻を引いたかが値に出る。"""
    lat = np.asarray(latitudes, dtype=float)
    lon = np.asarray(longitudes, dtype=float)
    return (lat - 35.0) * 10 * (1 + hour_index), (lon - 139.0) * 10 * (1 + hour_index)


def _patch_msm(monkeypatch, times: list[str] = TIMES) -> list[tuple[np.ndarray, np.ndarray]]:
    asked: list[tuple[np.ndarray, np.ndarray]] = []

    async def read_series(latitudes, longitudes, hours=None):
        asked.append((np.asarray(latitudes), np.asarray(longitudes)))
        u, v = zip(*(_wind_uv(latitudes, longitudes, h) for h in range(len(times))))
        count = len(latitudes)
        return times, {
            "wind_u_component_10m": np.stack(u, axis=1),
            "wind_v_component_10m": np.stack(v, axis=1),
            "precipitation": np.zeros((count, len(times))),
            "temperature_2m": np.full((count, len(times)), 20.0),
            "cloud_cover": np.zeros((count, len(times))),
        }

    monkeypatch.setattr(msm_client, "read_series", read_series)
    return asked


def _expected(grid_lat: float, grid_lon: float, hour_index: int, bearing_deg: float, speed_kmh: float) -> float:
    u, v = _wind_uv(grid_lat, grid_lon, hour_index)
    speed, direction = wind_speed_and_direction(u, v)
    return round(wind_drag_ratio(float(speed), float(direction), bearing_deg, kmh_to_ms(speed_kmh)), 3)


def _service(repository) -> WindWayService:
    return WindWayService(repository=repository, weather_service=WeatherService())


# 型が`float | None`なのは呼び出し口の形を揃えるためで、Noneのまま計算へ進ませない。
async def test_bearing_deg_none_raises_value_error():
    with pytest.raises(ValueError, match="bearing_deg"):
        await _service(FakeMidpointsRepository(None)).get_way_values(Z, X, Y, AT, None, SPEED_KMH)


async def test_speed_kmh_none_raises_value_error():
    with pytest.raises(ValueError, match="speed_kmh"):
        await _service(FakeMidpointsRepository(None)).get_way_values(Z, X, Y, AT, 0.0)


async def test_uncovered_tile_returns_empty_dict_without_reading_the_forecast(monkeypatch):
    asked = _patch_msm(monkeypatch)

    assert await _service(FakeMidpointsRepository(None)).get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH) == {}
    assert asked == []


async def test_covered_but_no_ways_returns_empty_dict(monkeypatch):
    _patch_msm(monkeypatch)

    assert await _service(FakeMidpointsRepository({})).get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH) == {}


async def test_each_way_takes_the_wind_of_the_grid_point_nearest_its_middle(monkeypatch):
    """同じタイルでも、中ほどが別の格子点に近い道は別の風を引く。タイルをまたいで中ほどが
    タイルの外にある道も、端の格子点へ寄せずに本当に近い点を引く。"""
    _patch_msm(monkeypatch)
    repository = FakeMidpointsRepository({
        "1": (35.674, 139.713),     # → (35.65, 139.6875)
        "2-0": (35.676, 139.735),   # → (35.70, 139.75)
        "3": (35.60, 139.80),       # タイルの外 → (35.60, 139.8125)
    })

    result = await _service(repository).get_way_values(Z, X, Y, AT, 45.0, 25.0)

    assert result == {
        "1": _expected(35.65, 139.6875, 1, 45.0, 25.0),
        "2-0": _expected(35.70, 139.75, 1, 45.0, 25.0),
        "3": _expected(35.60, 139.8125, 1, 45.0, 25.0),
    }
    assert len(set(result.values())) == 3


async def test_the_forecast_hour_nearest_the_chosen_time_is_used(monkeypatch):
    _patch_msm(monkeypatch)
    repository = FakeMidpointsRepository({"1": (35.674, 139.713)})

    result = await _service(repository).get_way_values(Z, X, Y, datetime(2026, 8, 30, 9, 40), 0.0, SPEED_KMH)

    assert result == {"1": _expected(35.65, 139.6875, 2, 0.0, SPEED_KMH)}


@pytest.mark.parametrize("at", [datetime(2026, 8, 30, 7, 20), datetime(2026, 8, 30, 10, 40), datetime(2027, 1, 1)])
async def test_a_time_outside_the_forecast_is_not_painted(monkeypatch, at):
    """ルートの区間は予報の先を端の値で延ばすが、地図は延ばした値で塗らない（「データなし」）。"""
    _patch_msm(monkeypatch)
    repository = FakeMidpointsRepository({"1": (35.674, 139.713)})

    assert await _service(repository).get_way_values(Z, X, Y, at, 0.0, SPEED_KMH) == {}


async def test_utc_aware_at_is_read_as_jst(monkeypatch):
    # 予報の時刻はJSTの壁時計時刻。tzinfoを剥がすだけで比べると時差ぶんずれ、範囲外と判定される。
    _patch_msm(monkeypatch)
    repository = FakeMidpointsRepository({"1": (35.674, 139.713)})
    at_utc = AT.replace(tzinfo=JST).astimezone(timezone.utc)

    result = await _service(repository).get_way_values(Z, X, Y, at_utc, 0.0, SPEED_KMH)

    assert result == {"1": _expected(35.65, 139.6875, 1, 0.0, SPEED_KMH)}


async def test_at_none_defaults_to_now(monkeypatch):
    now_hour = datetime.now(JST).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    times = [(now_hour + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(-1, 3)]
    _patch_msm(monkeypatch, times)
    repository = FakeMidpointsRepository({"1": (35.674, 139.713)})

    result = await _service(repository).get_way_values(Z, X, Y, None, 0.0, SPEED_KMH)

    assert set(result) == {"1"}


async def test_second_call_reads_the_forecast_again(monkeypatch):
    # 風の値はキャッシュせず、同じ条件でも都度計算する。
    asked = _patch_msm(monkeypatch)
    repository = FakeMidpointsRepository({"1": (35.674, 139.713)})
    service = _service(repository)

    first = await service.get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)
    second = await service.get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)

    assert first == second
    assert len(repository.calls) == 2 and len(asked) == 2


async def test_forecast_unavailable_returns_empty_dict(monkeypatch):
    async def unavailable(latitudes, longitudes, hours=None):
        raise MsmUnavailableError("未同期")

    monkeypatch.setattr(msm_client, "read_series", unavailable)
    repository = FakeMidpointsRepository({"1": (35.674, 139.713)})

    assert await _service(repository).get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH) == {}


async def test_repository_error_returns_empty_dict():
    repository = FakeMidpointsRepository(None, error=ConnectionRefusedError("db down"))

    assert await _service(repository).get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH) == {}


async def test_an_implementation_error_is_not_turned_into_an_empty_result():
    """DB障害でない例外まで空へ倒すと、利用者には「データなし」に見えて誰も気づかない。"""
    repository = FakeMidpointsRepository(None, error=TypeError("wrong arguments"))

    with pytest.raises(TypeError):
        await _service(repository).get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)
