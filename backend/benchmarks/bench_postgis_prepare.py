"""GraphService（`road_graph_use_repository`構成）のPostGIS経由prepare段階を、
実データ・実DB接続に対して計測する。

docs/architecture.mdは「東京都心4km周回でprepare 187秒」（Way分割の再計算＋Edge全量
再UPSERTが原因）を報告しているが、記録時点ではdev環境にPostGIS接続が無く未検証だった
（backend/benchmarks/README.md「わかったこと」4番参照）。dev機にネイティブPostgreSQL+
PostGISが用意され、`app/batch/import_pbf.py`で東京都心データを取込済みになったため、
このモジュールで実データに対して内訳（closureクエリ／build_road_graph／bulk UPSERT）を
分解して計測した（実測271秒、内訳はREADME参照）。

その結果を踏まえ、生データ不変時にroad_edges/road_nodesを直接読む省略パス
（`RoadGraphRepository.is_split_up_to_date`/`get_graph_in_bbox`、`GraphService`に配線済み）
を実装した。COLD（`split_at`をリセットした通常経路＝slow path）とWARM（省略パス＝
fast path）を分けて計測し、実データでの改善幅を確認する。

他のbenchmarksモジュールと異なり実際のPostGIS接続・DB書き込みを伴う（既存データと
同じ内容へのdelete-then-reinsertで冪等だが、合成データのみに閉じるという既存方針
からは外れる）ため、`run_all.py`には含めない。個別に実行すること。

前提: 対象bbox（東京駅周辺、下記ORIGIN_LAT/LON）が`app/batch/import_pbf.py`で
取込済みであること（docs/osm-pbf-import.md参照。カバー範囲外だとSKIPする）。

実行方法（backend/ディレクトリから。.envのDATABASE_URLはSupabase向けのため、
ローカルDBへ明示的に上書きする）:
    $env:DATABASE_URL = "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass"
    .venv\\Scripts\\python.exe -m benchmarks.bench_postgis_prepare
"""

from __future__ import annotations

import asyncio
import gc
import time

from benchmarks._harness import BenchmarkResult, print_report

# 取込済み範囲内（docs/osm-pbf-import.md記載のTokyo抽出カバー範囲）の東京駅。
# scripts/verify_phase1_e2e.pyと同じ起点。
ORIGIN_LAT = 35.681
ORIGIN_LON = 139.767


async def _measure_async(name: str, coro_fn, *, repeat: int, warmup: int = 0, note: str = "") -> BenchmarkResult:
    """`_harness.measure_async`と同じ計測ロジックだが、呼び出し側が既に持つイベント
    ループ内で使う（asyncio.runを内包しないため、DBセッション等を跨いで使い回せる）。
    """
    for _ in range(warmup):
        await coro_fn()

    samples: list[float] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(repeat):
            start = time.perf_counter()
            await coro_fn()
            samples.append(time.perf_counter() - start)
    finally:
        if gc_was_enabled:
            gc.enable()
    return BenchmarkResult(name=name, n=repeat, samples_s=samples, note=note)


async def _check_tiles_cached(repository, bbox) -> bool:
    from app.domain.region import ROAD_GRAPH_TILE_ZOOM, tiles_covering_bbox

    for x, y in tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM):
        if not await repository.is_tile_cached(ROAD_GRAPH_TILE_ZOOM, x, y):
            return False
    return True


async def _run_scenario(
    session_factory, distance_km: float, slow_repeat: int = 1, fast_repeat: int = 3
) -> list[BenchmarkResult]:
    """`slow_repeat`はclosure/build/save（1回あたり数十秒〜3分規模）に使う繰り返し回数、
    `fast_repeat`はis_split_up_to_date/WARM呼び出し（1回あたりms〜秒規模）に使う繰り返し
    回数。分けているのは、遅いステージをむやみに繰り返すと1回の実行が数十分規模になり
    試行錯誤の妨げになるため（実測で判明。デフォルトのslow_repeat=1は分散が取れない
    トレードオフだが、まずは1回でも実データでの規模感を掴むことを優先する）。"""
    from sqlalchemy import update

    from app.domain.graph import LeanRoadGraph, build_road_graph
    from app.domain.route import Coordinates
    from app.infrastructure.road_graph_models import OsmRawWayRow
    from app.infrastructure.road_graph_repository import RoadGraphRepository
    from app.services.graph_service import GraphService
    from app.services.road_graph_engine import BBOX_MARGIN_MIN_KM, BBOX_MARGIN_RATIO, _bbox_around_point
    from app.services.route_generator import RADIUS_RATIO

    origin = Coordinates(latitude=ORIGIN_LAT, longitude=ORIGIN_LON)
    # prepare()（road_graph_engine.py）と同じbbox算出式。実際のリクエストと同じ形・
    # 大きさのbboxを再現する（架空の縮尺で計測しても実運用の目安にならないため）。
    radius_km = distance_km * RADIUS_RATIO
    margin_km = max(BBOX_MARGIN_MIN_KM, radius_km * BBOX_MARGIN_RATIO)
    bbox = _bbox_around_point(origin, radius_km + margin_km)
    label = f"distance={distance_km}km"

    results: list[BenchmarkResult] = []

    async with session_factory() as probe_session:
        if not await _check_tiles_cached(RoadGraphRepository(probe_session), bbox):
            print(
                f"SKIP [{label}]: bbox({bbox.min_latitude:.2f},{bbox.min_longitude:.2f})-"
                f"({bbox.max_latitude:.2f},{bbox.max_longitude:.2f})に未取込タイルがある。"
                "app.batch.import_pbfで対象範囲を取込んでから再実行すること。"
            )
            return results

    # --- Stage 1: get_way_specs_with_closure（DB空間検索、主対象Way＋近傍Wayの取得） ---
    fetched: dict = {}

    async def _closure():
        async with session_factory() as session:
            fetched["value"] = await RoadGraphRepository(session).get_way_specs_with_closure(bbox)

    results.append(
        await _measure_async(
            f"[{label}] get_way_specs_with_closure (DB spatial query)", _closure, repeat=slow_repeat
        )
    )
    way_specs, node_coords, primary_way_ids = fetched["value"]
    scale_note = f"ways={len(way_specs)} nodes={len(node_coords)} primary_ways={len(primary_way_ids)}"
    results[-1].note = scale_note

    # --- Stage 2: build_road_graph（交差点分割、CPU） ---
    async def _build():
        build_road_graph(way_specs, node_coords)

    results.append(
        await _measure_async(
            f"[{label}] build_road_graph (intersection split)", _build, repeat=slow_repeat, note=scale_note
        )
    )

    graph = build_road_graph(way_specs, node_coords)
    primary_edges = {eid: e for eid, e in graph.edges.items() if e.osm_way_id in primary_way_ids}
    referenced_node_ids = {e.from_node_id for e in primary_edges.values()} | {
        e.to_node_id for e in primary_edges.values()
    }
    primary_nodes = {nid: n for nid, n in graph.nodes.items() if nid in referenced_node_ids}
    primary_graph = LeanRoadGraph(graph_version=graph.graph_version, nodes=primary_nodes, edges=primary_edges)
    edge_note = f"primary_edges={len(primary_edges)} primary_nodes={len(primary_nodes)}"

    # --- Stage 3: save_graph（bulk UPSERT、DB書き込み） ---
    # 既存データと同じ内容へのdelete-then-reinsertのため冪等（何度実行してもDBの内容は変わらない）。
    # surfaceは専用テーブルを持たず、road_edges.osm_way_id経由でosm_raw_ways.surfaceをJOIN導出する
    # ため（改善計画T9）、保存対象はsave_graphのみになった。
    async def _save():
        async with session_factory() as session:
            repo = RoadGraphRepository(session)
            await repo.save_graph(primary_graph, way_ids_to_replace=primary_way_ids)

    results.append(
        await _measure_async(f"[{label}] save_graph (bulk UPSERT)", _save, repeat=slow_repeat, note=edge_note)
    )

    # --- Stage 4: get_or_build_graph_with_attributes end-to-end（実際のprepare()と同じ呼び出し） ---
    # is_split_up_to_date（省略パス）により、生データ不変時はCOLD/WARMで所要時間が大きく
    # 異なるようになった。直前のStage 3（save_graph）でprimary_way_idsのsplit_atが既に
    # 刷新済み（＝WARM状態）のため、まずWARM（省略パス、fast path）を計測し、次に
    # split_atだけを明示的にリセット（updated_atには触れないためFinding Aの修正とは無関係。
    # 実運用でこの状態になるのは生データが実際に変わった場合のみ）してCOLD（通常経路、
    # slow path）を計測する。
    async def _end_to_end():
        async with session_factory() as session:
            service = GraphService(repository=RoadGraphRepository(session))
            built = await service.get_or_build_graph_with_attributes(bbox)
            assert built is not None and built[0].edges, "空グラフが返った(取込範囲を確認)"

    async def _is_split_up_to_date_only():
        async with session_factory() as session:
            await RoadGraphRepository(session).is_split_up_to_date(bbox)

    async def _reset_split_at():
        # asyncpgのプリペアド文パラメータ上限（32767個）を超えないよう、
        # road_graph_repository.pyの_ID_CHUNK_SIZEと同じ考え方でチャンク分割する
        # （4kmシナリオではprimary_way_idsが35,202件あり、無分割だと超過してエラーになる）。
        id_chunk_size = 10_000
        sorted_ids = sorted(primary_way_ids)
        async with session_factory() as session:
            for start in range(0, len(sorted_ids), id_chunk_size):
                chunk = sorted_ids[start : start + id_chunk_size]
                await session.execute(
                    update(OsmRawWayRow).where(OsmRawWayRow.osm_way_id.in_(chunk)).values(split_at=None)
                )
            await session.commit()

    results.append(
        await _measure_async(
            f"[{label}] is_split_up_to_date alone (freshness check, WARM)",
            _is_split_up_to_date_only,
            repeat=fast_repeat,
            note=edge_note,
        )
    )
    results.append(
        await _measure_async(
            f"[{label}] get_or_build_graph_with_attributes end-to-end WARM (fast path: skips closure/build/save)",
            _end_to_end,
            repeat=fast_repeat,
            note=edge_note,
        )
    )

    await _reset_split_at()
    results.append(
        await _measure_async(
            f"[{label}] get_or_build_graph_with_attributes end-to-end COLD (split_at reset, full slow path)",
            _end_to_end,
            repeat=1,
            note=edge_note,
        )
    )

    return results


async def run() -> list[BenchmarkResult]:
    from app.infrastructure.database import get_engine, get_session_factory

    session_factory = get_session_factory()
    results: list[BenchmarkResult] = []
    try:
        # BBOX_MARGIN_MIN_KM=2kmが下限のため、1km周回でも4km周回とbboxの大きさは
        # さほど変わらない（＝小さい周回でも同程度の重さになる、という副次的な発見）。
        # slow_repeat=1（既定値）: closure/build/saveは1回あたり数十秒〜3分規模のため、
        # 繰り返し回数を増やすと全体の実行時間が試行錯誤に耐えない規模になる。
        results += await _run_scenario(session_factory, distance_km=1.0)
        results += await _run_scenario(session_factory, distance_km=4.0)
    finally:
        await get_engine().dispose()
    return results


if __name__ == "__main__":
    print_report(
        "PostGIS-backed GraphService.get_or_build_graph_with_attributes: real local DB, real Tokyo import data",
        asyncio.run(run()),
    )
