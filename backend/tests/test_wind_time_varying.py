"""探索中の風評価の時変化（通過予定時刻の静的推定＋往路/復路別コスト配列）。"""
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.domain.evaluation import DynamicAxisRequestContext, RoutePreference, evaluate_dynamic_material_arrays
from app.domain.route import Coordinates
from app.domain.weather import WeatherConditions
from app.domain.wind import WindForecastSeries, estimate_passage_hours, kmh_to_ms, wind_drag_ratio
from app.infrastructure import search_graph_cache
from app.services.weather_service import WeatherService
from tests.test_road_graph_engine import ORIGIN, _prepare_context, build_loop_graph, make_generator


@pytest.fixture(autouse=True)
def _clear_search_graph_cache():
    search_graph_cache.clear()
    yield
    search_graph_cache.clear()

START = datetime(2026, 9, 5, 9, 0)


def _series(hours: int, direction_by_hour) -> WindForecastSeries:
    times = [START.replace(hour=0) + timedelta(hours=h) for h in range(hours)]
    return WindForecastSeries(
        times=times,
        speed_ms=np.full(hours, 5.0),
        direction_deg=np.array([float(direction_by_hour(h)) for h in range(hours)]),
    )


def _weather(direction_deg: float) -> WeatherConditions:
    return WeatherConditions(
        temperature_c=20.0, apparent_temperature_c=None, wind_speed_ms=5.0, wind_direction_deg=direction_deg,
        wind_direction_label="北", wind_gusts_ms=None, precipitation_probability_percent=None,
        precipitation_mm=None, uv_index=None, observed_at="t",
        weather_code=None, is_day=None,
        sunrise=None, sunset=None, precipitation_probability_max_percent=None, wind_speed_max_ms=None,
        temperature_max_c=None, temperature_min_c=None,
        uv_index_max=None, today_periods=[],
    )


# --- domain/wind.py ---


def test_series_sample_picks_nearest_hour_and_clamps_to_range():
    series = _series(24, lambda h: h * 10)  # 0時=0°, 1時=10°, ...

    speed, direction = series.sample(START, np.array([0.0, 0.4, 0.6, 5.0, 100.0, -50.0]))

    assert speed.tolist() == [5.0] * 6
    # 9:00基準: +0h→9時(90°)、+0.4h→9時、+0.6h→10時、+5h→14時、範囲外は末尾(23時)・先頭(0時)へ
    assert direction.tolist() == [90.0, 90.0, 100.0, 140.0, 230.0, 0.0]


def test_series_rejects_non_hourly_or_mismatched_lengths():
    with pytest.raises(ValueError):
        WindForecastSeries(times=[START, START + timedelta(hours=2)], speed_ms=np.zeros(2), direction_deg=np.zeros(2))
    with pytest.raises(ValueError):
        WindForecastSeries(times=[START, START + timedelta(hours=1)], speed_ms=np.zeros(2), direction_deg=np.zeros(3))


def test_estimate_passage_hours_outbound_grows_and_inbound_shrinks_with_distance():
    anchor = Coordinates(latitude=35.0, longitude=139.0)
    # 北へ約11.1km（緯度0.1°）と約22.2kmの2地点
    mid_lat = np.array([35.1, 35.2])
    mid_lon = np.array([139.0, 139.0])

    outbound = estimate_passage_hours(mid_lat, mid_lon, anchor, 0.0, +1, 20.0, detour_ratio=1.0)
    inbound = estimate_passage_hours(mid_lat, mid_lon, anchor, 3.0, -1, 20.0, detour_ratio=1.0)

    assert outbound[0] == pytest.approx(11.1 / 20, abs=0.01)
    assert outbound[1] == pytest.approx(22.2 / 20, abs=0.02)
    assert inbound[0] == pytest.approx(3.0 - 11.1 / 20, abs=0.01)
    assert inbound[1] < inbound[0] < 3.0
    # 迂回率は時間へ比例して効く
    assert estimate_passage_hours(mid_lat, mid_lon, anchor, 0.0, +1, 20.0, detour_ratio=1.3)[0] == pytest.approx(
        outbound[0] * 1.3
    )
    with pytest.raises(ValueError):
        estimate_passage_hours(mid_lat, mid_lon, anchor, 0.0, +1, 0.0)


# --- domain/evaluation.py ---


V20 = kmh_to_ms(20.0)


def test_dynamic_materials_use_series_at_each_edge_passage_time():
    # 0〜11時は北風（0°）、12時以降は南風（180°）。北向き（bearing=0）のEdgeは、通過が12時以降
    # なら追い風（負）になる。二乗則材料と非推奨エイリアスの両方が同じ風入力から求まる。
    series = _series(24, lambda h: 0 if h < 12 else 180)
    bearing = np.array([0.0, 0.0])
    context = DynamicAxisRequestContext(
        bearing_deg=bearing, weather=_weather(0.0), travel_speed_ms=V20, wind_series=series, start=START,
        passage_hours=np.array([1.0, 4.0]),  # 10時・13時
    )

    materials = evaluate_dynamic_material_arrays(context)

    assert materials["wind_penalty"][0] == pytest.approx(5.0)  # 向かい風
    assert materials["wind_penalty"][1] == pytest.approx(-5.0)  # 追い風
    assert materials["wind_drag_ratio"][0] == pytest.approx(wind_drag_ratio(5.0, 0.0, 0.0, V20))
    assert materials["wind_drag_ratio"][1] == pytest.approx(wind_drag_ratio(5.0, 180.0, 0.0, V20))


def test_dynamic_materials_fall_back_to_snapshot_without_passage_hours():
    series = _series(24, lambda h: 180)
    context = DynamicAxisRequestContext(
        bearing_deg=np.array([0.0]), weather=_weather(0.0), travel_speed_ms=V20, wind_series=series,
    )

    materials = evaluate_dynamic_material_arrays(context)
    assert materials["wind_penalty"][0] == pytest.approx(5.0)
    assert materials["wind_drag_ratio"][0] == pytest.approx(wind_drag_ratio(5.0, 0.0, 0.0, V20))

    no_weather = evaluate_dynamic_material_arrays(
        DynamicAxisRequestContext(bearing_deg=np.array([0.0]), weather=None, travel_speed_ms=V20)
    )
    assert np.isnan(no_weather["wind_penalty"][0]) and np.isnan(no_weather["wind_drag_ratio"][0])


def test_dynamic_context_requires_travel_speed():
    # 走行速度の伝播漏れは既定値で黙って計算せず、構築時点で失敗する。
    with pytest.raises(TypeError):
        DynamicAxisRequestContext(bearing_deg=np.array([0.0]), weather=_weather(0.0))  # type: ignore[call-arg]


# --- services/weather_service.py ---


class _Client:
    def __init__(self, data):
        self._data = data

    async def get_forecast(self, http_client, point):
        return self._data


async def test_get_wind_forecast_series_parses_hourly_wind():
    data = {
        "hourly": {
            "time": ["2026-09-05T00:00", "2026-09-05T01:00", "2026-09-05T02:00"],
            "wind_speed_10m": [1.0, 2.0, 3.0],
            "wind_direction_10m": [10.0, 20.0, 30.0],
        }
    }
    service = WeatherService(_Client(data), http_client=None)

    series = await service.get_wind_forecast_series(ORIGIN)

    assert series is not None
    assert series.times[1] == datetime(2026, 9, 5, 1, 0)
    assert series.speed_ms.tolist() == [1.0, 2.0, 3.0]
    assert series.direction_deg.tolist() == [10.0, 20.0, 30.0]


@pytest.mark.parametrize(
    "data",
    [
        None,
        {"hourly": {"time": ["2026-09-05T00:00"], "wind_speed_10m": [1.0], "wind_direction_10m": [1.0]}},  # 2点未満
        {"hourly": {"time": ["2026-09-05T00:00", "2026-09-05T01:00"], "wind_speed_10m": [1.0, None], "wind_direction_10m": [1.0, 2.0]}},
        {"hourly": {"time": ["2026-09-05T00:00", "2026-09-05T01:00"], "wind_speed_10m": [1.0, 2.0]}},
    ],
)
async def test_get_wind_forecast_series_returns_none_for_unusable_data(data):
    service = WeatherService(_Client(data), http_client=None)

    assert await service.get_wind_forecast_series(ORIGIN) is None


# --- services/road_graph_engine.py ---


def _wind_only_preference() -> RoutePreference:
    weights = {axis_id: 0.0 for axis_id in RoutePreference().weights}
    weights["wind"] = 1.0
    return RoutePreference(weights=weights)


async def test_prepare_shares_snapshot_leg_when_wind_axis_has_no_weight():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    weights = {axis_id: 0.0 for axis_id in RoutePreference().weights}
    weights["gradient"] = 1.0
    generator, _, _ = make_generator(
        graph, weather=_weather(0.0), wind_series=_series(48, lambda h: 0), route_preference=RoutePreference(weights=weights),
    )
    engine = generator._engine
    context = await _prepare_context(generator)

    assert context.composer.time_varying is False
    await engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=8)

    assert len(context.legs) == 2
    assert context.legs[1] is context.legs[0]  # 追加の合成無し


async def test_lens_axis_forces_time_varying_even_when_wind_weight_is_zero():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    weights = {axis_id: 0.0 for axis_id in RoutePreference().weights}
    weights["gradient"] = 1.0
    generator, _, _ = make_generator(
        graph, weather=_weather(0.0), wind_series=_series(48, lambda h: 0),
        route_preference=RoutePreference(weights=weights), lens_axis_id="wind",
    )
    context = await _prepare_context(generator)

    assert context.composer.time_varying is True
    await generator._engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=8)
    assert context.legs[1] is not context.legs[0]  # 復路は復路の時刻の風で別途合成される


async def test_inbound_leg_uses_wind_at_return_time_and_segments_read_the_same_arrays():
    # 出発9時、周回30km（20km/hで1.5時間）。10時以降に北風→南風へ反転する系列にすると、
    # 北向きスポーク（中点は起点から7.5km、迂回率1.3で通過まで約0.49h）は往路では9:29
    # （北風）、復路では起点到着1.5hの0.49h前＝10:01（南風）として評価される。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    series = _series(48, lambda h: 0 if h < 10 else 180)
    generator, _, _ = make_generator(
        graph, weather=_weather(0.0), wind_series=series, route_preference=_wind_only_preference(),
    )
    engine = generator._engine
    # prepare()の`now`はUTC。9:00 JST = 0:00 UTC。
    context = await engine.prepare(ORIGIN, radius_km=30.0 * 0.4, now=datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc))
    assert context is not None and context.composer.time_varying

    turnarounds = await engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=8)
    assert len(context.legs) == 2 and context.legs[1] is not context.legs[0]
    outbound, inbound = context.legs

    # 北向きスポーク（origin→p-0、bearing 0°）: 往路配列では向かい風（+5）、復路配列では
    # 復路の通過予定時刻（10:01→最近傍10時=南風）の追い風（-5）。
    row = context.full_edge_row["e-0-spoke1"]
    assert outbound.material_arrays["wind_penalty"][row] == pytest.approx(5.0)
    assert inbound.material_arrays["wind_penalty"][row] == pytest.approx(-5.0)
    assert outbound.cost_list != inbound.cost_list

    # 区間表示は各Edgeが探索されたレグの配列から読む（往路Edgeは往路配列、復路Edgeは復路配列）。
    turnaround = next((t for t in turnarounds if t.bearing == 0), turnarounds[0])
    traced = await engine.trace_loop_from_turnaround(context, turnaround)
    assert traced.leg_of_edge == [0] + [1] * (len(traced.data) - 1)
    candidates = await engine.evaluate_loops(context, [traced], datetime(2026, 9, 5, 9, 0))
    segments = candidates[0].segments
    first, last = segments[0], segments[-1]
    # 風軸の重み>0なので、区間のmaterial_valuesに風軸が参照する材料(wind_penalty)が出る
    # （候補全体への集約はroute_generator.pyが行うため、engine.evaluate_loopsが返す
    # 時点ではsegments側だけで確認する）。
    assert "wind_penalty" in first.material_values and "wind_penalty" in last.material_values


async def test_material_values_omits_wind_when_wind_axis_has_no_weight():
    # 改善計画T592: 風軸の重みが0のリクエストでは、風データ自体はあっても
    # material_valuesに風の材料(wind_penalty)は出ない（評価に使っていない軸の材料は
    # 出ない、という規約）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    weights = {axis_id: 0.0 for axis_id in RoutePreference().weights}
    weights["gradient"] = 1.0
    series = _series(48, lambda h: 0)
    generator, _, _ = make_generator(
        graph, weather=_weather(0.0), wind_series=series,
        route_preference=RoutePreference(weights=weights),
    )
    engine = generator._engine
    context = await engine.prepare(ORIGIN, radius_km=30.0 * 0.4, now=datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc))
    assert context is not None

    turnarounds = await engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=8)
    turnaround = turnarounds[0]
    traced = await engine.trace_loop_from_turnaround(context, turnaround)
    candidates = await engine.evaluate_loops(context, [traced], datetime(2026, 9, 5, 9, 0))

    for segment in candidates[0].segments:
        assert "wind_penalty" not in segment.material_values


async def test_assumed_speed_changes_estimated_arrival_time_and_preview_duration():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    slow, _, _ = make_generator(graph, assumed_speed_kmh=20.0)
    fast, _, _ = make_generator(graph, assumed_speed_kmh=40.0)

    slow_candidates = await slow.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0, max_routes=1)
    fast_candidates = await fast.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0, max_routes=1)

    slow_last = datetime.fromisoformat(slow_candidates[0].segments[-1].estimated_arrival_time)
    fast_last = datetime.fromisoformat(fast_candidates[0].segments[-1].estimated_arrival_time)
    slow_start = datetime.fromisoformat(slow_candidates[0].segments[0].estimated_arrival_time)
    fast_start = datetime.fromisoformat(fast_candidates[0].segments[0].estimated_arrival_time)
    slow_elapsed = (slow_last - slow_start).total_seconds()
    fast_elapsed = (fast_last - fast_start).total_seconds()
    assert slow_elapsed > 0
    assert fast_elapsed == pytest.approx(slow_elapsed / 2, rel=0.05)

    preview_slow = await slow._engine.preview_segment(ORIGIN, Coordinates(latitude=graph.nodes["p-0"].latitude, longitude=graph.nodes["p-0"].longitude))
    preview_fast = await fast._engine.preview_segment(ORIGIN, Coordinates(latitude=graph.nodes["p-0"].latitude, longitude=graph.nodes["p-0"].longitude))
    assert preview_slow is not None and preview_fast is not None
    assert preview_fast.duration_minutes == pytest.approx(preview_slow.duration_minutes / 2, rel=0.05)
    assert not math.isnan(preview_slow.duration_minutes)


# --- 迂回率の実測値化 ---

TILE_SET = frozenset({(12, 3637, 1612)})


async def test_inbound_leg_uses_measured_detour_ratio_and_learns_it_for_next_request():
    # 車輪状フィクスチャのスポークは直線なので、リングNodeの実測迂回率はちょうど1.0。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    series = _series(48, lambda h: 0 if h < 10 else 180)
    generator, _, _ = make_generator(
        graph, weather=_weather(0.0), wind_series=series, route_preference=_wind_only_preference(), tile_set=TILE_SET,
    )
    engine = generator._engine
    context = await engine.prepare(ORIGIN, radius_km=30.0 * 0.4, now=datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc))
    assert context is not None
    assert context.composer.detour_ratio == pytest.approx(1.3)  # 学習前は既定値

    await engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=8)

    assert search_graph_cache.get_detour_ratio(TILE_SET) == pytest.approx(1.0)
    outbound, inbound = context.legs
    row = context.full_edge_row["e-0-spoke1"]
    # 往路は既定値1.3、復路は実測1.0で通過予定時刻を推定する（スポーク中点は起点から7.5km）。
    assert outbound.passage_hours[row] == pytest.approx(1.3 * 7.5 / 20, abs=0.01)
    assert inbound.passage_hours[row] == pytest.approx(1.5 - 1.0 * 7.5 / 20, abs=0.01)

    # 同じタイル集合への次のリクエストは往路にも学習値を使う。
    second = await engine.prepare(ORIGIN, radius_km=30.0 * 0.4, now=datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc))
    assert second.composer.detour_ratio == pytest.approx(1.0)
    assert second.legs[0].passage_hours[row] == pytest.approx(1.0 * 7.5 / 20, abs=0.01)


async def test_detour_ratio_is_not_learned_without_tile_set():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(
        graph, weather=_weather(0.0), wind_series=_series(48, lambda h: 0), route_preference=_wind_only_preference(),
    )
    engine = generator._engine
    context = await _prepare_context(generator)

    await engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=8)

    assert context.tile_set is None
    assert context.legs[1].passage_hours is not None  # 復路は実測値で合成される
    assert search_graph_cache.get_detour_ratio(TILE_SET) is None


def test_search_graph_cache_detour_ratio_roundtrip_and_invalidation():
    search_graph_cache.set_detour_ratio(TILE_SET, 1.21)
    assert search_graph_cache.get_detour_ratio(TILE_SET) == pytest.approx(1.21)
    search_graph_cache.invalidate_tile_set(TILE_SET)
    assert search_graph_cache.get_detour_ratio(TILE_SET) is None
    search_graph_cache.set_detour_ratio(TILE_SET, 1.21)
    search_graph_cache.clear()
    assert search_graph_cache.get_detour_ratio(TILE_SET) is None
