"""`infrastructure/cache_db.py`（標高キャッシュ、SQLite）の計測。

修正前は`cache_db._connect()`が`get_elevation`/`set_elevation`が呼ばれるたびに新規sqlite3
接続（+ `PRAGMA journal_mode=WAL` + `CREATE TABLE IF NOT EXISTS`実行）を張り直す実装だった。
現在はスレッドローカルに接続を1本キャッシュして使い回す方式に修正済み（`cache_db._get_connection`）。
`ElevationAttributeService`はEdgeのgeometry上の形状点1つにつき1回このキャッシュを引くため、
Road Graphルーティングで1候補あたり数十〜数百回、8方位分だとその数倍呼ばれうる。

(a) 本番実装（修正後）を連続呼び出しした場合の1呼び出しあたりのコスト
(b) 比較用に「asyncio.to_threadのディスパッチも無い、単一接続の同期実装」（このベンチマーク
    内だけの比較用コード。本番コードには手を入れない）で同じ処理をした場合のコスト
を並べて、修正後もなお残る差（主に`asyncio.to_thread`のスレッドプールディスパッチ
オーバーヘッド）がどれだけかを見る。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from benchmarks._harness import BenchmarkResult, measure_async, print_report

POINT_COUNTS = [50, 200, 800]


def _persistent_connection_variant(db_path: Path):
    """cache_db.get_elevation/set_elevationと同じSQL・スキーマだが、接続を1本だけ張って
    使い回す比較用の実装（本番のcache_db.pyには手を入れない）。"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS elevation_cache (
            lat REAL NOT NULL, lon REAL NOT NULL, elevation_m REAL, fetched_at TEXT NOT NULL,
            PRIMARY KEY (lat, lon)
        )"""
    )
    conn.commit()

    def get(lat: float, lon: float):
        row = conn.execute("SELECT elevation_m FROM elevation_cache WHERE lat = ? AND lon = ?", (lat, lon)).fetchone()
        return None if row is None else row[0]

    def set_(lat: float, lon: float, elevation_m: float | None):
        conn.execute(
            "INSERT OR REPLACE INTO elevation_cache (lat, lon, elevation_m, fetched_at) VALUES (?, ?, ?, ?)",
            (lat, lon, elevation_m, "2025-01-01T00:00:00Z"),
        )
        conn.commit()

    return get, set_, conn


def run(tmp_dir: Path | None = None) -> list[BenchmarkResult]:
    import tempfile

    from app.infrastructure import cache_db

    results: list[BenchmarkResult] = []
    base_dir = tmp_dir or Path(tempfile.mkdtemp(prefix="ridecompass_bench_"))

    for n in POINT_COUNTS:
        points = [(35.0 + i * 0.0001, 139.0 + i * 0.0001) for i in range(n)]

        # (a) 本番実装（cache_db.py、修正後）: get_elevationを1点ずつ呼ぶ（スレッドローカルで
        # 接続を使い回す。asyncio.to_threadのディスパッチ自体のオーバーヘッドは残る）。
        db_path_a = base_dir / f"a_{n}.db"
        cache_db.DATA_DIR = base_dir
        cache_db.DB_PATH = db_path_a
        # 事前に1回書き込んでおき、以降は「ヒットするget」のコストを計測する
        # （書き込みも同じ接続コストを負うため、書き込みのみのベンチは別途行う）。
        _run_sync(_seed_all(cache_db, points))

        async def get_all_current(cache_db=cache_db, points=points):
            for lat, lon in points:
                await cache_db.get_elevation(lat, lon)

        results.append(
            measure_async(
                f"cache_db.get_elevation x{n} (production code, connection reused per thread)",
                get_all_current,
                repeat=8,
                warmup=1,
            )
        )

        # (b) 比較用: 接続を使い回す実装で同じget x n回。
        db_path_b = base_dir / f"b_{n}.db"
        get_b, set_b, conn_b = _persistent_connection_variant(db_path_b)
        for lat, lon in points:
            set_b(lat, lon, 12.3)

        async def get_all_persistent(get_b=get_b, points=points):
            for lat, lon in points:
                get_b(lat, lon)

        results.append(
            measure_async(
                f"comparison: persistent sqlite3 connection x{n} (bench-only, not production code)",
                get_all_persistent,
                repeat=8,
                warmup=1,
            )
        )
        conn_b.close()

    return results


async def _seed_all(cache_db, points):
    for lat, lon in points:
        await cache_db.set_elevation(lat, lon, 12.3)


def _run_sync(coro):
    import asyncio

    asyncio.run(coro)


def _make_edge_graph(edge_count: int, points_per_edge: int):
    """`ElevationAttributeService.get_attributes_for_graph`向けの合成RoadGraph。
    各Edgeにpoints_per_edge個の形状点（geometry）を持たせる（実際のOSM Wayの
    形状点密度を模す。build_road_graphは経由しないため交差点分割ロジックは対象外）。
    """
    from app.domain.graph import DirectedEdge, Node, RoadGraph

    nodes: dict[str, Node] = {}
    edges: dict[str, DirectedEdge] = {}
    for i in range(edge_count):
        from_id, to_id = f"n{i}-a", f"n{i}-b"
        base_lat, base_lon = 35.0 + i * 0.01, 139.0
        geometry = [[base_lat + j * 0.0002, base_lon + j * 0.0002] for j in range(points_per_edge)]
        nodes[from_id] = Node(node_id=from_id, latitude=geometry[0][0], longitude=geometry[0][1])
        nodes[to_id] = Node(node_id=to_id, latitude=geometry[-1][0], longitude=geometry[-1][1])
        edge_id = f"e{i}"
        edges[edge_id] = DirectedEdge(
            edge_id=edge_id, from_node_id=from_id, to_node_id=to_id, geometry=geometry, distance_m=100.0
        )
    return RoadGraph(graph_version="bench", nodes=nodes, edges=edges)


def run_service(edge_counts: list[int] | None = None, points_per_edge: int = 6) -> list[BenchmarkResult]:
    """`ElevationAttributeService.get_attributes_for_graph`をend-to-endに近い形で計測する。

    実ネットワーク（GSI API）は呼ばず`ElevationClient._fetch`だけ差し替えて即値を返す
    （計測対象はcache_db往復 + asyncio.gather/Semaphoreのオーケストレーションのみに絞るため）。
    これは`RoadGraphEngine._build_candidate`が候補（8方位）ごとに呼ぶ処理そのものに相当する。
    """
    import tempfile

    import httpx

    from app.infrastructure import cache_db
    from app.infrastructure.elevation_client import ElevationClient
    from app.services.elevation_attribute_service import ElevationAttributeService

    class InstantElevationClient(ElevationClient):
        async def _fetch(self, client, point):  # noqa: D401 - 比較用のネットワーク省略スタブ
            return 42.0

    base_dir = Path(tempfile.mkdtemp(prefix="ridecompass_bench_service_"))
    cache_db.DATA_DIR = base_dir
    cache_db.DB_PATH = base_dir / "service.db"

    results: list[BenchmarkResult] = []
    for edge_count in edge_counts or [30, 120, 480]:
        graph = _make_edge_graph(edge_count, points_per_edge)
        client = InstantElevationClient()

        async def one_candidate(graph=graph, client=client):
            async with httpx.AsyncClient() as http_client:
                service = ElevationAttributeService(client, http_client)
                await service.get_attributes_for_graph(graph)

        results.append(
            measure_async(
                f"ElevationAttributeService.get_attributes_for_graph "
                f"(edges={edge_count}, points/edge={points_per_edge}, warm cache after 1st call)",
                one_candidate,
                repeat=5,
                warmup=1,
            )
        )

    return results


if __name__ == "__main__":
    print_report("cache_db (elevation SQLite cache): per-call connection overhead", run())
    print_report(
        "ElevationAttributeService.get_attributes_for_graph: end-to-end (network stubbed)", run_service()
    )
