"""`api/routers/routes.py`——ルート生成のHTTPの入口。

確かめるのは、HTTPから見える振る舞いだけ: 要求の検証（422）、ジョブの投稿と取得（202・404）、生成の種類
（周回・目的地・経由地・区間の乗り換え）の振り分け、実際に使った条件のエコー、候補0件の理由、失敗の伝え方、
同時実行とレート制限（429）。

裏の生成は本物の`RouteGenerator`とエンジンを、小さな格子の道路網（`tests/route_world.py`）の上で通す。
差し替えるのはプロセス境界だけ——DBのセッションと天気の予報ファイル（生成の開き方の注入の口`get_route_generation_setup_opener`）・
道路網の置き場・レート制限の記録。

ここで見ないもの:
- 経路の中身（周回が閉じる・一方通行・重みの効き等） → `test_route_generation_behavior.py`
- 候補の並べ方・理由の文面 → `test_route_generator.py`
- レート制限の数え方そのもの → `test_rate_limiter.py`
- 重みの値の検査（公開軸のidだけ・非負） → `test_route_preference.py`。ここでは寄せていることを1行で見る
- 項目ごとの値の範囲（距離・件数等の`Field`の制約）→ 型の宣言が持つ
- 本物の開き方（`api/dependencies.py`がDBのセッションと天気を開いて渡すだけの結線。判断を持たない）
"""

import asyncio
import math
import re
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
import pytest

from app.api import dependencies
from app.config import settings
from app.domain.geo import haversine_distance_km
from app.domain.hard_filters import DEFAULT_HARD_FILTERS, HARD_FILTER_NAMES
from app.domain.route_request import DEFAULT_DISTANCE_TOLERANCE_KM, DEFAULT_MAX_ROUTES, MAX_SPLICED_EDGES, MAX_WAYPOINTS
from app.domain.tuning import TUNING_VALUES
from app.domain.wind import ASSUMED_SPEED_KMH
from app.infrastructure import rate_limiter, road_network_store
from app.infrastructure.road_network_store import RoadNetworkUnavailableError
from app.main import app
from app.services.graph_service import GraphService
from app.services.route_generation_setup import assemble_route_generation_setup
from tests.route_world import (
    AVOID_AXIS,
    CENTER,
    NORTH_EAST,
    SOUTH_WEST,
    NetworkRepository,
    Weather,
    at,
    avoid_axis_declared,
    grid_network,
)

#: ASGIの代役がHTTPの相手として名乗る番地（レート制限の鍵になる）。
CLIENT_HOST = "127.0.0.1"
FAR_AWAY = {"latitude": 35.80, "longitude": 139.80}  # 格子から約25km。道が無い
BEYOND_REACH = {"latitude": 37.0, "longitude": 139.8}  # 格子から100km超
JAPANESE = re.compile(r"[぀-ヿ一-鿿]")  # かな・漢字
#: 画面がいつも送る欄（値は画面の既定）。
ALWAYS_SENT = {
    "distance_tolerance_km": DEFAULT_DISTANCE_TOLERANCE_KM,
    "hard_filters": {name: name in DEFAULT_HARD_FILTERS for name in HARD_FILTER_NAMES},
    "max_routes": DEFAULT_MAX_ROUTES,
    "assumed_speed_kmh": ASSUMED_SPEED_KMH,
    "start_time": "2026-09-22T08:00:00+09:00",
}


def _point(osm_node_id):
    coordinates = at(osm_node_id)
    return {"latitude": coordinates.latitude, "longitude": coordinates.longitude}


class World:
    """道路網の置き場と天気の代役。`network`を差し替えると次の生成から効く。"""

    def __init__(self):
        self.network = grid_network()
        self.unavailable = False
        self.weather = Weather()

    def current(self):
        if self.unavailable:
            raise RoadNetworkUnavailableError("道路網の置き場がありません")
        return self.network


class GatedWeather(Weather):
    """開くまで生成を止めておく天気の代役（同時実行の上限を観るため）。"""

    def __init__(self):
        super().__init__()
        self.gate = asyncio.Event()

    async def get_departure_wind(self, origin):
        await self.gate.wait()
        return None


@pytest.fixture
def world(monkeypatch):
    """格子の道路網・天気の代役と、避けたい材料を読む公開軸1本（`avoid_axis_declared`）。"""
    world = World()

    @asynccontextmanager
    async def open_setup(**options):
        yield assemble_route_generation_setup(GraphService(NetworkRepository(world.network)), world.weather, **options)

    monkeypatch.setattr(road_network_store, "current", world.current)
    monkeypatch.setitem(app.dependency_overrides, dependencies.get_route_generation_setup_opener, lambda: open_setup)
    with avoid_axis_declared():
        yield world


@pytest.fixture
async def client(world):
    """`world`の上で動くアプリへのHTTPの口。"""
    transport = httpx.ASGITransport(app=app, client=(CLIENT_HOST, 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _post(client, **body):
    return await client.post("/api/routes/generate", json={**_point(CENTER), "distance_km": 4.0, **ALWAYS_SENT, **body})


async def _wait(client, job_id):
    for _ in range(1000):
        status = (await client.get(f"/api/routes/generate/{job_id}")).json()
        if status["status"] in ("done", "failed"):
            return status
        await asyncio.sleep(0.01)
    raise AssertionError("ジョブが終わらない")


async def _generate(client, **body):
    response = await _post(client, **body)
    assert response.status_code == 202, response.text
    return await _wait(client, response.json()["job_id"])


def _ends(route):
    return route["node_ids"][0], route["node_ids"][-1]


def _node(osm_node_id):
    return f"osm-node-{osm_node_id}"


# --- 生成の種類 ---


async def test_a_loop_is_generated_when_neither_destination_nor_waypoints_are_given(client):
    result = (await _generate(client))["result"]

    assert result["routes"]
    assert all(_ends(route) == (_node(CENTER), _node(CENTER)) for route in result["routes"])
    assert result["no_candidates_reason"] is None


async def test_a_destination_route_ends_at_the_destination_with_up_to_the_requested_count(client):
    result = (await _generate(client, **_point(SOUTH_WEST), destination=_point(NORTH_EAST), max_routes=2))["result"]

    assert 1 <= len(result["routes"]) <= 2
    assert result["conditions"]["max_routes"] == 2
    assert all(_ends(route) == (_node(SOUTH_WEST), _node(NORTH_EAST)) for route in result["routes"])


async def test_a_waypoint_route_is_a_single_route_whatever_count_is_asked_for(client):
    """経由地があるとレグごとの代替案が組合せで増えるため、常に1件。使った件数もそう返す。"""
    status = await _generate(client, **_point(SOUTH_WEST), waypoints=[_point(NORTH_EAST)], max_routes=5)

    assert len(status["result"]["routes"]) == 1
    assert status["result"]["conditions"]["max_routes"] == 1


async def test_a_spliced_route_is_evaluated_as_sent(client):
    """区間を差し替えた経路は探索し直さず、そのまま1件として評価して返す。"""
    body = {**_point(SOUTH_WEST), "destination": _point(NORTH_EAST)}
    (route, *_) = (await _generate(client, **body, max_routes=1))["result"]["routes"]

    spliced = (await _generate(client, **body, spliced_edge_ids=route["edge_ids"]))["result"]

    assert [r["edge_ids"] for r in spliced["routes"]] == [route["edge_ids"]]


async def test_an_empty_result_says_why(client):
    status = await _generate(client, distance_km=30.0, destination=FAR_AWAY)

    assert status["status"] == "done"
    assert status["result"]["routes"] == []
    assert status["result"]["no_candidates_reason"]


# --- 条件のエコー ---


async def test_the_defaults_that_were_applied_are_echoed(client):
    """画面が見る値と探索が使った値を分けない。省略した項目も、実際に使った値で返す。"""
    conditions = (await _generate(client))["result"]["conditions"]

    assert conditions["route_preference"] == {AVOID_AXIS: 0.0}
    assert conditions["waypoints"] is None and conditions["destination"] is None
    assert conditions["corrected_destination"] is None


async def test_the_overrides_that_were_sent_are_echoed(client):
    """保存したレスポンスの条件をそのまま送り直せば、同じ条件で生成し直せる。"""
    hard_filters = {name: False for name in HARD_FILTER_NAMES}
    conditions = (await _generate(
        client, route_preference={AVOID_AXIS: 2.0}, penalty_strength=0.5, max_average_grade_percent=8.0,
        hard_filters=hard_filters, assumed_speed_kmh=25.0, distance_tolerance_km=2.0,
    ))["result"]["conditions"]

    assert conditions["route_preference"] == {AVOID_AXIS: 2.0}
    assert conditions["penalty_strength"] == 0.5
    assert conditions["max_average_grade_percent"] == 8.0
    assert conditions["hard_filters"] == hard_filters
    assert conditions["assumed_speed_kmh"] == 25.0
    assert conditions["distance_tolerance_km"] == 2.0


async def test_an_omitted_rate_is_the_calibrated_value_at_the_time_of_generation(client, monkeypatch):
    """管理画面で変えた較正値は、プロセスを入れ替えずに次の生成から効き、使った値として返る。"""
    monkeypatch.setitem(TUNING_VALUES, "evaluation.penalty_strength", 0.37)
    first = (await _generate(client))["result"]["conditions"]["penalty_strength"]
    monkeypatch.setitem(TUNING_VALUES, "evaluation.penalty_strength", 0.61)
    second = (await _generate(client))["result"]["conditions"]["penalty_strength"]

    assert (first, second) == (0.37, 0.61)


@pytest.mark.parametrize(("sent", "applied"), [
    ("2026-09-22T08:00:00", "2026-09-22T08:00:00+09:00"),          # 時差の無い値は日本時間
    ("2026-09-21T23:00:00+00:00", "2026-09-22T08:00:00+09:00"),    # 時差のある値は日本時間へ直す
])
async def test_the_departure_time_is_read_in_japan_time(client, sent, applied):
    conditions = (await _generate(client, start_time=sent))["result"]["conditions"]

    assert datetime.fromisoformat(conditions["start_time"]) == datetime.fromisoformat(applied)
    assert conditions["start_time"].endswith("+09:00")


async def test_a_destination_route_searches_as_far_as_the_farthest_point_whatever_distance_is_sent(client):
    """点を置いたときの距離は探索の範囲で、backendが点から決める（最も遠い点の距離を切り上げて1km足す）。"""
    origin = at(SOUTH_WEST)
    farthest = max(haversine_distance_km(origin, at(node)) for node in (CENTER, NORTH_EAST))
    conditions = (await _generate(
        client, **_point(SOUTH_WEST), waypoints=[_point(CENTER)], destination=_point(NORTH_EAST), distance_km=0.5,
    ))["result"]["conditions"]

    assert conditions["distance_km"] == math.ceil(farthest) + 1


async def test_a_destination_moved_to_the_nearest_reachable_road_is_echoed(client, world):
    world.network = grid_network(island=True)

    conditions = (await _generate(client, **_point(SOUTH_WEST), destination=_point(91)))["result"]["conditions"]

    assert conditions["corrected_destination"] == _point(NORTH_EAST)
    assert conditions["destination"] == _point(91)


# --- 要求の検証 ---


@pytest.mark.parametrize("body", [
    {"route_preference": {}},                                        # 公開軸を全部書いていない
    {"route_preference": {AVOID_AXIS: -1.0}},                        # 値の検査（`check_axis_weights`）へ寄せている
    {"hard_filters": {}},
    {"spliced_edge_ids": ["way-100-seg0-fwd"]},                       # 目的地が無い
    {"distance_km": None},                                           # 周回なのに目標距離が無い
])
async def test_a_request_outside_what_can_be_generated_is_refused_before_any_job(client, body):
    response = await _post(client, **body)

    assert response.status_code == 422


@pytest.mark.parametrize("body", [
    {"waypoints": [_point(CENTER)] * (MAX_WAYPOINTS + 1)},
    {"destination": BEYOND_REACH},
    {"destination": _point(NORTH_EAST), "spliced_edge_ids": ["way-100-seg0-fwd"] * (MAX_SPLICED_EDGES + 1)},
])
async def test_a_limit_reached_by_placing_points_is_refused_in_words_the_rider_reads(client, body):
    """画面は誤りの文をそのまま結果欄へ出す。前置き（「Value error, 」）の付かない日本語の文だけが返る。"""
    response = await _post(client, **body)

    messages = [error["msg"] for error in response.json()["detail"]]
    assert response.status_code == 422
    assert messages and all(JAPANESE.search(m) and not m.startswith("Value error") for m in messages)


# --- ジョブ ---


async def test_a_job_that_is_not_known_is_404(client):
    assert (await client.get("/api/routes/generate/no-such-job")).status_code == 404


async def test_a_failed_job_says_so_without_leaking_its_internals(client, world):
    """例外の中身（接続先・SQL）はログだけに残す。失敗しても同時実行の枠は返る（上限より多く続けて投げても受け付ける）。"""
    world.unavailable = True

    statuses = [await _generate(client) for _ in range(settings.generate_max_concurrent + 1)]

    assert {s["status"] for s in statuses} == {"failed"}
    assert all("置き場" not in s["error"] and s["error"] for s in statuses)


async def test_jobs_beyond_the_concurrency_limit_are_refused_at_once(client, world):
    """待たせずに429を返す（連打やブラウザのリトライで裏の負荷を積み上げない）。枠が空けばまた受け付ける。"""
    world.weather = GatedWeather()
    running = [await _post(client) for _ in range(settings.generate_max_concurrent)]

    # 上限を越えた投稿が枠の空きを待ってしまうと、応答が返らない。待たせないことを期限で確かめる。
    refused = await asyncio.wait_for(_post(client), timeout=5)

    world.weather.gate.set()
    for response in running:
        assert response.status_code == 202
        assert (await _wait(client, response.json()["job_id"]))["status"] == "done"
    assert refused.status_code == 429
    assert (await _generate(client))["status"] == "done"


async def test_too_many_requests_from_one_client_are_refused(client):
    for _ in range(settings.generate_rate_limit_per_minute - 1):
        rate_limiter.check_rate_limit(f"generate:{CLIENT_HOST}", settings.generate_rate_limit_per_minute)

    assert (await _generate(client))["status"] == "done"
    assert (await _post(client)).status_code == 429
