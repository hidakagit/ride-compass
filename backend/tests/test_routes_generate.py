from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import RouteGenerationSetup, _assemble_route_generation_setup
from app.api.routers import routes as routes_module
from app.api.routers.routes import _generate_semaphore
from app.config import settings
from app.domain.evaluation import DEFAULT_HARD_FILTERS, RoutePreference
from app.domain.route import RouteCandidate
from app.infrastructure import job_registry, rate_limiter
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.ors_client import ORSClient
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.weather_client import WeatherClient
from app.main import app
from app.services.elevation_attribute_service import ElevationAttributeService
from app.services.elevation_service import ElevationService
from app.services.evaluation_service import load_route_preference
from app.services.graph_service import GraphService
from app.services.route_scorer import load_scoring_weights
from app.services.routing_service import RoutingService
from app.services.weather_service import WeatherService
from app.services.wind_service import WindService

# 改善計画T350: 本番相当の14軸（実軸id前提のロジック用）はtests/conftest.pyのセッション
# スコープautouseフィクスチャが全テスト共通で用意する（tests/realistic_axis_fixtures.py参照）。

client = TestClient(app)

REQUEST_BODY = {
    "latitude": 35.7597,
    "longitude": 139.7387,
    "distance_km": 30,
    "distance_tolerance_km": 5,
    "route_type": "loop",
}

DEFAULT_SCORING_WEIGHTS = {
    "distance_weight": 0.30,
    "elevation_weight": 0.15,
    "wind_weight": 0.30,
    "road_weight": 0.25,
}


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    # rate_limiterはプロセス内グローバルの固定窓カウンタのため、テスト間で
    # 消し込まないと前のテストのリクエストが今のテストの上限に食い込む。
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeRouteGenerator:
    engine_name = "fake-engine"

    def __init__(self, candidates: list[RouteCandidate]):
        self._candidates = candidates

    async def generate_loops(self, origin, distance_km, distance_tolerance_km):
        return self._candidates


def fake_open_route_generation_setup(candidates: list[RouteCandidate], captured: dict | None = None):
    """`open_route_generation_setup`（改善計画T265、バックグラウンドジョブが使う
    非同期コンテキストマネージャ）のフェイク版。`captured`を渡すと、ジョブへ渡された
    重み上書き（無ければNone）を記録する。"""

    @asynccontextmanager
    async def _open(
        preference_override=None,
        scoring_weights_override=None,
        penalty_strength: float = 1.0,
        max_average_grade_percent: float | None = None,
        hard_filters_override: frozenset[str] | None = None,
    ):
        if captured is not None:
            captured["preference"] = preference_override
            captured["scoring"] = scoring_weights_override
            captured["penalty_strength"] = penalty_strength
            captured["max_average_grade_percent"] = max_average_grade_percent
            captured["hard_filters"] = hard_filters_override
        yield RouteGenerationSetup(
            generator=FakeRouteGenerator(candidates),
            scoring_weights=scoring_weights_override or DEFAULT_SCORING_WEIGHTS,
            route_preference=preference_override or RoutePreference(),
            penalty_strength=penalty_strength,
            max_average_grade_percent=max_average_grade_percent,
            hard_filters=hard_filters_override if hard_filters_override is not None else DEFAULT_HARD_FILTERS,
        )

    return _open


def submit_and_await_done(body: dict) -> dict:
    """POST /api/routes/generateでジョブを投稿し、GET /api/routes/generate/{job_id}で
    status=="done"になった結果を返す（改善計画T265）。`BackgroundTasks`は`TestClient`の
    リクエストサイクル内で同期的に実行されるため、ポーリングのための待機は不要——
    投稿直後の1回のGETで結果が確定している。"""
    submit_response = client.post("/api/routes/generate", json=body)
    assert submit_response.status_code == 202, submit_response.text
    job_id = submit_response.json()["job_id"]
    poll_response = client.get(f"/api/routes/generate/{job_id}")
    assert poll_response.status_code == 200, poll_response.text
    payload = poll_response.json()
    assert payload["status"] == "done", payload
    return payload["result"]


def test_generate_routes_returns_candidates_and_engine(monkeypatch):
    candidates = [
        RouteCandidate(
            id="route-000",
            direction_label="北",
            distance_km=29.8,
            geometry={"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.8]]},
        )
    ]
    monkeypatch.setattr(routes_module, "open_route_generation_setup", fake_open_route_generation_setup(candidates))

    result = submit_and_await_done(REQUEST_BODY)

    assert len(result["routes"]) == 1
    assert result["routes"][0]["id"] == "route-000"
    assert result["routes"][0]["direction_label"] == "北"
    assert result["engine"] == "fake-engine"


def test_generate_routes_returns_empty_list_when_no_candidates_match(monkeypatch):
    monkeypatch.setattr(routes_module, "open_route_generation_setup", fake_open_route_generation_setup([]))

    result = submit_and_await_done(REQUEST_BODY)

    assert result["routes"] == []
    assert result["engine"] == "fake-engine"


def test_generate_routes_echoes_applied_conditions(monkeypatch):
    # 実験の記録・再現用に、実際に適用された条件（重み含む）をレスポンスへエコーする
    # （研究インターフェース改善 §10-6）。上書き無しの場合は既定重みがそのまま入る。
    monkeypatch.setattr(routes_module, "open_route_generation_setup", fake_open_route_generation_setup([]))

    conditions = submit_and_await_done(REQUEST_BODY)["conditions"]

    assert conditions["latitude"] == REQUEST_BODY["latitude"]
    assert conditions["longitude"] == REQUEST_BODY["longitude"]
    assert conditions["distance_km"] == REQUEST_BODY["distance_km"]
    assert conditions["distance_tolerance_km"] == REQUEST_BODY["distance_tolerance_km"]
    assert conditions["scoring_weights"] == DEFAULT_SCORING_WEIGHTS
    # RoutePreferenceWeightsはRootModel(dict)のため、レスポンスではaxis_idキーの
    # プレーンな辞書としてシリアライズされる（改善計画T221 Stage B）。
    assert conditions["route_preference"] == RoutePreference().weights
    # ISO8601（JST）。厳密な時刻は環境依存のため形式だけ確認する
    assert "+09:00" in conditions["generated_at"]


def test_generate_routes_applies_weight_overrides_and_echoes_them(monkeypatch):
    # リクエストの重み上書きがジョブへ渡り、conditionsに適用値がエコーされる
    # （研究インターフェース改善 §10-1）。
    captured: dict = {}
    monkeypatch.setattr(routes_module, "open_route_generation_setup", fake_open_route_generation_setup([], captured))
    scoring_weights = {"distance_weight": 0.1, "elevation_weight": 0.2, "wind_weight": 0.3, "road_weight": 0.4}
    route_preference = {
        "gradient": 0.5, "surface_q": 0.25, "wind": 0.2, "stop_density": 0.05,
        "car_stress": 0.0, "accident": 0.0,
        "night": 0.0, "bicycle_infra_quality": 0.0,
    }

    result = submit_and_await_done(
        {**REQUEST_BODY, "scoring_weights": scoring_weights, "route_preference": route_preference}
    )

    assert captured["scoring"] == scoring_weights
    assert captured["preference"] == RoutePreference(weights=route_preference)
    conditions = result["conditions"]
    assert conditions["scoring_weights"] == scoring_weights
    assert conditions["route_preference"] == route_preference


def test_generate_routes_echoes_default_hard_filters_when_omitted(monkeypatch):
    # 改善計画T266: hard_filters省略時はDEFAULT_HARD_FILTERS（全フィルタ有効）が
    # そのままconditionsへエコーされる。
    monkeypatch.setattr(routes_module, "open_route_generation_setup", fake_open_route_generation_setup([]))

    conditions = submit_and_await_done(REQUEST_BODY)["conditions"]

    assert conditions["hard_filters"] == {"no_bicycle": True, "motorway": True, "trunk": True}


def test_generate_routes_applies_hard_filters_override_and_echoes_them(monkeypatch):
    # 改善計画T266: hard_filtersの個別ON/OFF上書きがジョブへ渡り、conditionsへ
    # 適用値がエコーされる。
    captured: dict = {}
    monkeypatch.setattr(routes_module, "open_route_generation_setup", fake_open_route_generation_setup([], captured))
    hard_filters = {"no_bicycle": True, "motorway": True, "trunk": False}

    result = submit_and_await_done({**REQUEST_BODY, "hard_filters": hard_filters})

    assert captured["hard_filters"] == frozenset({"no_bicycle", "motorway"})
    assert result["conditions"]["hard_filters"] == hard_filters


def test_generate_routes_rejects_hard_filters_with_missing_keys():
    # RoutePreferenceWeightsと同じ「上書きするなら全項目を明示する」方針
    # （改善計画T266）。リクエストボディの検証はジョブ作成前に働くため、フェイクの
    # 差し替え無しでも422になる。
    response = client.post("/api/routes/generate", json={**REQUEST_BODY, "hard_filters": {"no_bicycle": True}})

    assert response.status_code == 422


def test_generate_routes_is_rate_limited_per_client():
    # ルート生成は最も高コストなエンドポイント（外部APIクォータ・数十秒の処理時間）のため、
    # per-IPの上限を超えたリクエストは429で拒否する（ジョブ作成前、投稿時点の同期チェック）。
    for _ in range(settings.generate_rate_limit_per_minute - 1):
        rate_limiter.check_rate_limit("generate:testclient", settings.generate_rate_limit_per_minute)
    assert client.post("/api/routes/generate", json=REQUEST_BODY).status_code == 202

    response = client.post("/api/routes/generate", json=REQUEST_BODY)

    assert response.status_code == 429


async def test_generate_routes_rejects_when_concurrency_limit_reached():
    # 同時実行数の上限に達している間は待たせず429を返す（外部サービスへの負荷の積み上げ防止）。
    # 改善計画T265: この判定はジョブ作成前・投稿時点のまま変更していない。
    acquired = 0
    try:
        while not _generate_semaphore.locked():
            await _generate_semaphore.acquire()
            acquired += 1
        response = client.post("/api/routes/generate", json=REQUEST_BODY)
    finally:
        for _ in range(acquired):
            _generate_semaphore.release()

    assert response.status_code == 429


def test_generate_routes_acquires_semaphore_before_scheduling_background_job(monkeypatch):
    # 改善計画T386（T265コードレビュー指摘1件目、CONFIRMED回帰テスト）: 以前は
    # POSTハンドラで`_generate_semaphore.locked()`を確認するだけで、実際の取得
    # （`async with _generate_semaphore:`）は`BackgroundTasks`経由でレスポンス送出後に
    # 実行される`_run_generate_job`側だった。両者の間にHTTPレスポンス送出という実I/Oが
    # 挟まるため、複数リクエストがほぼ同時に届くと上限を超える数が202で受理されうる
    # レースがあった（ASGITransport上のin-memory送受信は実I/Oを伴わずawaitでも
    # 中断しないため、httpx.AsyncClientでの並行リクエスト再現は非現実的——このテストは
    # 代わりに「バックグラウンドジョブが動き出す時点で、セマフォが既にPOSTハンドラ側で
    # 減算済みである」という、レースを構造的に閉じている不変条件を直接検証する）。
    observed_semaphore_values: list[int] = []

    async def _fake_run_generate_job(job_id: str, request) -> None:
        # 本物の_run_generate_jobを丸ごと差し替える。観測した時点で既に取得済みなら、
        # POSTハンドラ側での同期取得が効いている証拠になる。取得した分はここで解放し
        # テスト後の状態を元に戻す（本物のfinally節と同じ役割）。
        observed_semaphore_values.append(_generate_semaphore._value)
        job_registry.set_done(job_id, None)
        _generate_semaphore.release()

    monkeypatch.setattr(routes_module, "_run_generate_job", _fake_run_generate_job)

    response = client.post("/api/routes/generate", json=REQUEST_BODY)

    assert response.status_code == 202
    assert observed_semaphore_values == [settings.generate_max_concurrent - 1]
    assert _generate_semaphore._value == settings.generate_max_concurrent


def test_generate_job_status_returns_404_for_unknown_job_id():
    # 改善計画T265: 完了から時間が経過して破棄された、またはそもそも存在しないjob_idは
    # 404（例外を握りつぶさず、フロントがポーリングを打ち切れるようにする）。
    response = client.get("/api/routes/generate/does-not-exist")

    assert response.status_code == 404


def test_generate_job_status_returns_failed_with_generic_error_message(monkeypatch):
    # 改善計画T265: バックグラウンドジョブ内の例外はレスポンスへ伝播できないため、
    # job_registryへ記録してポーリング側がstatus=="failed"として観測できることを確認する。
    # 改善計画T386（T265コードレビュー指摘3件目、CONFIRMED）: 例外の生メッセージ
    # （openrouteserviceの生レスポンス本文等を含みうる）はクライアントへ公開せず、
    # 汎用メッセージのみを返す。詳細はlogger.exceptionでサーバーログにのみ残す。
    @asynccontextmanager
    async def _raise_setup(*args, **kwargs):
        raise RuntimeError("生成中に想定外のエラー（本来ログにのみ残るべき内部詳細）")
        yield  # noqa: このasynccontextmanagerがジェネレータであるためのダミーyield（到達しない）

    monkeypatch.setattr(routes_module, "open_route_generation_setup", _raise_setup)

    submit_response = client.post("/api/routes/generate", json=REQUEST_BODY)
    assert submit_response.status_code == 202
    job_id = submit_response.json()["job_id"]
    poll_response = client.get(f"/api/routes/generate/{job_id}")

    assert poll_response.status_code == 200
    body = poll_response.json()
    assert body["status"] == "failed"
    assert "生成中に想定外のエラー" not in body["error"]
    assert body["error"] == "ルート生成に失敗しました。時間をおいて再度お試しください。"


def test_generate_job_failure_releases_concurrency_semaphore(monkeypatch):
    # 改善計画T386（T265コードレビュー指摘1件目、CONFIRMED）: セマフォは投稿時点の
    # POSTハンドラで取得するようになった（TOCTOUレース対応）ため、ジョブが例外で
    # 終わった場合でも_run_generate_job側のfinallyで確実に解放され、リークしないことを
    # 確認する（リークすると同時実行枠が徐々に埋まり、無関係な後続リクエストが429に
    # なっていく）。
    @asynccontextmanager
    async def _raise_setup(*args, **kwargs):
        raise RuntimeError("失敗")
        yield  # noqa: このasynccontextmanagerがジェネレータであるためのダミーyield（到達しない）

    monkeypatch.setattr(routes_module, "open_route_generation_setup", _raise_setup)

    submit_response = client.post("/api/routes/generate", json=REQUEST_BODY)
    job_id = submit_response.json()["job_id"]
    poll_response = client.get(f"/api/routes/generate/{job_id}")
    assert poll_response.json()["status"] == "failed"

    assert not _generate_semaphore.locked()
    assert _generate_semaphore._value == settings.generate_max_concurrent


def _lightweight_route_generation_setup(preference_override=None, scoring_weights_override=None):
    # _assemble_route_generation_setupはFastAPIのDependsで解決される前提の依存を
    # 直接渡して呼べる純粋関数（改善計画T265でget_route_generation_builderのクロージャから
    # 抽出）。「settings.routing_engineに応じたエンジン選択」と重みの既定値/上書きの反映
    # だけを検証する。いずれの依存もコンストラクタではI/Oを行わないため、http_client・
    # session（RoadGraphRepository）はNoneでよい。
    return _assemble_route_generation_setup(
        routing_service=RoutingService(ORSClient("test-key", http_client=None)),
        elevation_service=ElevationService(ElevationClient(), http_client=None),
        wind_service=WindService(WeatherService(WeatherClient(), http_client=None)),
        graph_service=GraphService(repository=RoadGraphRepository(session=None)),
        elevation_attribute_service=ElevationAttributeService(ElevationClient(), http_client=None),
        weather_service=WeatherService(WeatherClient(), http_client=None),
        surface_match_repository=None,
        preference_override=preference_override,
        scoring_weights_override=scoring_weights_override,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"latitude": 91},
        {"latitude": -91},
        {"longitude": 181},
        {"longitude": -181},
        {"distance_km": 0},
        {"distance_km": -5},
        {"distance_tolerance_km": 0},
        {"route_type": "not-a-real-type"},
        # 重み上書きは非負のみ許可。部分指定（フィールド欠け）は「クラス既定値が黙って入る」
        # 事故を避けるため全フィールド必須（routes.py: RoutePreferenceWeights参照）
        {"scoring_weights": {"distance_weight": -0.1, "elevation_weight": 0.2, "wind_weight": 0.3, "road_weight": 0.4}},
        {"scoring_weights": {"distance_weight": 0.5}},
        {"route_preference": {"elevation_weight": 0.5, "road_weight": -0.1, "wind_weight": 0.25}},
        {"route_preference": {"elevation_weight": 0.5}},
    ],
)
def test_generate_routes_rejects_invalid_request_body(overrides):
    # リクエストボディの検証はジョブ作成前に働くため、フェイクの差し替え無しでも422になる。
    response = client.post("/api/routes/generate", json={**REQUEST_BODY, **overrides})

    assert response.status_code == 422


def test_generation_setup_selects_engine_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "routing_engine", "openrouteservice")
    assert _lightweight_route_generation_setup().generator.engine_name == "openrouteservice"

    monkeypatch.setattr(settings, "routing_engine", "road_graph")
    assert _lightweight_route_generation_setup().generator.engine_name == "road_graph"


def test_generation_setup_uses_yaml_defaults_when_no_override():
    setup = _lightweight_route_generation_setup()

    assert setup.scoring_weights == load_scoring_weights()
    assert setup.route_preference == load_route_preference()


def test_generation_setup_uses_overrides_when_provided():
    preference = RoutePreference(weights={"gradient": 1.0, "surface_q": 0.0, "wind": 0.0})
    scoring_weights = {"distance_weight": 1.0, "elevation_weight": 0.0, "wind_weight": 0.0, "road_weight": 0.0}

    setup = _lightweight_route_generation_setup(preference, scoring_weights)

    assert setup.route_preference is preference
    assert setup.scoring_weights == scoring_weights
