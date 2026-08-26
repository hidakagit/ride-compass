"""ORS(openrouteservice)エンジンとroad_graphエンジンの経路品質比較検証（改善計画T236）。

ORSから独自の検索エンジン（road_graph）への完全移行を判断する材料として、両エンジンで
同一の起点・距離を与えたときの成功率・目標距離への追従精度・所要時間を定量比較する。
HTTP経由ではなく、dependencies.pyのget_route_generation_builderと同じ組み立て方で両エンジンを
直接Pythonで構築し、RouteGenerator.generate_loopsを呼ぶ。road_graphエンジンは実際のAPIリクエスト
と同じく呼び出しごとに新規DBセッションを使う（1つのセッションを全呼び出しで使い回すと、
長時間の保持で接続がタイムアウトすることが実行時に判明したため）。

前提: dev DB（PostGIS、対象範囲を取込済み）・OPENROUTESERVICE_API_KEYが有効であること。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\compare_engines_quality.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402
from app.domain.route import Coordinates  # noqa: E402
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository  # noqa: E402
from app.infrastructure.database import get_engine, get_session_factory  # noqa: E402
from app.infrastructure.elevation_client import ElevationClient  # noqa: E402
from app.infrastructure.ors_client import ORSClient  # noqa: E402
from app.infrastructure.road_graph_repository import RoadGraphRepository  # noqa: E402
from app.infrastructure.weather_client import WeatherClient  # noqa: E402
from app.services.axis_registry_service import refresh_axis_definitions  # noqa: E402
from app.services.elevation_attribute_service import ElevationAttributeService  # noqa: E402
from app.services.elevation_service import ElevationService  # noqa: E402
from app.services.evaluation_service import EvaluationService, load_route_preference  # noqa: E402
from app.services.graph_service import GraphService  # noqa: E402
from app.services.openrouteservice_engine import OpenRouteServiceEngine  # noqa: E402
from app.services.road_graph_engine import RoadGraphEngine  # noqa: E402
from app.services.route_generator import RouteGenerator  # noqa: E402
from app.services.route_scorer import RouteScorer, load_scoring_weights  # noqa: E402
from app.services.routing_service import RoutingService  # noqa: E402
from app.services.weather_service import WeatherService  # noqa: E402
from app.services.wind_service import WindService  # noqa: E402

# 東京都心3地点（いずれもdev DB取込範囲内・実データあり）。
ORIGINS = {
    "王子": Coordinates(latitude=35.7597, longitude=139.7387),
    "新宿": Coordinates(latitude=35.6905, longitude=139.7005),
    "門前仲町": Coordinates(latitude=35.6730, longitude=139.7950),
}
DISTANCES_KM = [10.0, 20.0, 30.0]
DISTANCE_TOLERANCE_KM = 5.0


async def run_ors(
    http_client: httpx.AsyncClient, session_factory, origin: Coordinates, distance_km: float
) -> dict:
    preference = load_route_preference()
    # 改善計画T328で発見: dependencies.py: get_route_generation_builderは
    # road_graph_use_repository=True構成下でORSエンジンにもsurface_match_repositoryを
    # 注入し、路面・停止・交差点・事故の空間マッチ評価を有効化する（openrouteservice_engine.py
    # の`repository`引数）。本スクリプトはこれまでrepositoryを渡していなかったため、
    # road_graph側だけフル評価・ORS側は評価軸が欠落した非対称比較になっていた。
    # run_road_graphと同じく呼び出しごとに新規セッションを使う。
    async with session_factory() as surface_match_session:
        engine = OpenRouteServiceEngine(
            RoutingService(ORSClient(settings.openrouteservice_api_key, http_client)),
            ElevationService(ElevationClient(), http_client),
            WindService(WeatherService(WeatherClient(), http_client)),
            preference,
            repository=RoadGraphRepository(surface_match_session),
        )
        generator = RouteGenerator(engine, RouteScorer(load_scoring_weights()))
        return await run_one(generator, origin, distance_km)


async def run_road_graph(
    http_client: httpx.AsyncClient, session_factory, origin: Coordinates, distance_km: float
) -> dict:
    preference = load_route_preference()
    # 実際のAPIリクエストと同じく、呼び出しごとに新規セッションを使う（GraphService/
    # ElevationAttributeServiceの寿命を1回のgenerate_loops呼び出しに閉じる）。
    async with session_factory() as graph_session, session_factory() as elevation_session:
        engine = RoadGraphEngine(
            GraphService(repository=RoadGraphRepository(graph_session)),
            ElevationAttributeService(
                ElevationClient(), http_client, repository=RoadGraphRepository(elevation_session)
            ),
            EvaluationService(preference),
            WeatherService(WeatherClient(), http_client),
            preference,
        )
        generator = RouteGenerator(engine, RouteScorer(load_scoring_weights()))
        return await run_one(generator, origin, distance_km)


async def run_one(generator: RouteGenerator, origin: Coordinates, distance_km: float) -> dict:
    started = time.perf_counter()
    candidates = await generator.generate_loops(
        origin=origin, distance_km=distance_km, distance_tolerance_km=DISTANCE_TOLERANCE_KM
    )
    elapsed = time.perf_counter() - started
    errors_pct = [abs(c.distance_km - distance_km) / distance_km * 100 for c in candidates]
    return {
        "candidates": len(candidates),
        "elapsed_s": elapsed,
        "mean_error_pct": sum(errors_pct) / len(errors_pct) if errors_pct else None,
        "max_error_pct": max(errors_pct) if errors_pct else None,
    }


def _print_result(origin_name: str, engine_name: str, distance_km: float, result: dict) -> None:
    if result["candidates"]:
        print(
            f"{origin_name:>6} {engine_name:>16} {distance_km:>5.0f}km: "
            f"candidates={result['candidates']}/8 "
            f"elapsed={result['elapsed_s']:.1f}s "
            f"mean_err={result['mean_error_pct']:.1f}% "
            f"max_err={result['max_error_pct']:.1f}%",
            flush=True,
        )
    else:
        print(f"{origin_name:>6} {engine_name:>16} {distance_km:>5.0f}km: candidates=0/8", flush=True)


async def main() -> int:
    engine = get_engine()
    session_factory = get_session_factory()

    # 改善計画T350: AXIS_DEFINITIONSはDBからのpush型更新でのみ埋まる（Python literal撤去済み）。
    # 本スクリプトはapp.mainのlifespanを経由しない単体ツールのため、ここで明示的に読み込まないと
    # load_route_preference()がweights={}の空の軸重みを返し、両エンジンとも軸を一切考慮しない
    # 無意味な比較になってしまう（DB接続不可時はrefresh_axis_definitions自身がfail-fastする）。
    async with session_factory() as axis_session:
        await refresh_axis_definitions(AxisDefinitionRepository(axis_session))

    rows: list[tuple[str, str, float, dict]] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            for origin_name, origin in ORIGINS.items():
                for distance_km in DISTANCES_KM:
                    for engine_name in ("openrouteservice", "road_graph"):
                        try:
                            if engine_name == "openrouteservice":
                                result = await run_ors(http_client, session_factory, origin, distance_km)
                            else:
                                result = await run_road_graph(http_client, session_factory, origin, distance_km)
                        except Exception as exc:  # noqa: BLE001 比較検証なので1件の失敗で全体を止めない
                            print(f"{origin_name:>6} {engine_name:>16} {distance_km:>5.0f}km: ERROR {exc!r}", flush=True)
                            continue
                        rows.append((origin_name, engine_name, distance_km, result))
                        _print_result(origin_name, engine_name, distance_km, result)
    finally:
        await engine.dispose()

    print()
    print("=== まとめ（エンジン別平均） ===")
    for engine_name in ("openrouteservice", "road_graph"):
        engine_rows = [r for r in rows if r[1] == engine_name]
        if not engine_rows:
            print(f"{engine_name:>16}: 結果なし（全件エラー）")
            continue
        candidates = [r[3]["candidates"] for r in engine_rows]
        elapsed = [r[3]["elapsed_s"] for r in engine_rows]
        errors = [r[3]["mean_error_pct"] for r in engine_rows if r[3]["mean_error_pct"] is not None]
        summary = (
            f"成功率={sum(candidates)}/{len(candidates) * 8} "
            f"平均所要時間={sum(elapsed) / len(elapsed):.1f}s"
        )
        if errors:
            summary += f" 平均距離誤差={sum(errors) / len(errors):.1f}%"
        print(f"{engine_name:>16}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
