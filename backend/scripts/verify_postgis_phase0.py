"""Phase 0検証スクリプト: 実PostGISに対するdatabase.py / road_graph_repository.pyの動作確認。

docs/osm-pbf-import.md「9. 段階的導入計画」のPhase 0。これまで実DBに対して一度も
実行されていなかった以下を、実際のPostGIS（PostgreSQL 18 + PostGIS 3.6）で検証する:

- create_tables()（PostGIS拡張の有効化・DDL・GIN/空間インデックス作成の冪等性）
- save_raw_ways / get_way_specs_with_closure（GINインデックスの&&検索・1ホップ近傍closure）
- save_graph（Session.mergeによるUPSERT・FK制約・delete-then-reinsert）
- get_graph_in_bbox（ST_Intersects/ST_MakeEnvelope・ジオメトリ往復での緯度経度軸順）
- elevation/surface attributesの保存・読込（timestamptz往復を含む）
- is_tile_cached / mark_tile_cached
- GraphService.get_or_build_graph_with_attributes（タイルキャッシュのオーケストレーション一式）

実行方法（backendディレクトリから）:
    $env:DATABASE_URL = "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass"
    .venv\\Scripts\\python.exe scripts\\verify_postgis_phase0.py

書き込みはすべて架空のOSM ID（910兆/920兆台）で行い、終了時に削除する
（road_graph_tilesへの取得済みマークも削除するため、実運用データを汚さない）。
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.domain.attributes import ElevationAttribute  # noqa: E402
from app.domain.graph import RoadGraph, WaySpec, build_road_graph  # noqa: E402
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, BoundingBox, tiles_covering_bbox  # noqa: E402
from app.domain.osm_adapter import osm_ways_to_way_specs  # noqa: E402
from app.infrastructure.database import get_engine, get_session_factory  # noqa: E402
from app.infrastructure.migrate import apply_pending_migrations  # noqa: E402
from app.infrastructure.road_graph_repository import RoadGraphRepository, create_tables  # noqa: E402
from app.services.graph_service import GraphService  # noqa: E402

# --- 検証用フィクスチャ（実OSMデータと衝突しない巨大ID） ---
N1, N2, N3, N4, N5, N6 = (910_000_000_001, 910_000_000_002, 910_000_000_003,
                          910_000_000_004, 910_000_000_005, 910_000_000_006)
WAY_A, WAY_B, WAY_C = 920_000_000_001, 920_000_000_002, 920_000_000_003
FIXTURE_NODE_IDS = [N1, N2, N3, N4, N5, N6]
FIXTURE_WAY_IDS = [WAY_A, WAY_B, WAY_C]

NODE_COORDS: dict[int, tuple[float, float]] = {
    N1: (35.0000, 139.0000),
    N2: (35.0000, 139.0010),
    N3: (35.0000, 139.0020),  # bbox外（東側）
    N4: (34.9990, 139.0010),
    N5: (35.0010, 139.0010),
    N6: (35.0005, 139.0030),  # bbox外（C専用）
}

# A: N1-N2-N3の東西路。B: N4-N2-N5の南北路（N2でAと交差）。
# C: N3-N6の一方通行路（bbox外のN3でAとノード共有 → 1ホップclosureでのみ見つかる）。
WAY_SPECS = [
    WaySpec(osm_way_id=WAY_A, node_ids=[N1, N2, N3], highway="residential", surface="asphalt", direction="both"),
    WaySpec(osm_way_id=WAY_B, node_ids=[N4, N2, N5], highway="residential", surface=None, direction="both"),
    WaySpec(osm_way_id=WAY_C, node_ids=[N3, N6], highway="service", surface="gravel", direction="forward"),
]

# N1, N2, N4, N5を含みN3, N6を含まないbbox
BBOX = BoundingBox(
    min_latitude=34.9985, min_longitude=138.9995, max_latitude=35.0015, max_longitude=139.0015
)

FIXTURE_TILE = (ROAD_GRAPH_TILE_ZOOM, 987_654, 123_456)  # タイルマーカー単体検証用の架空タイル

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}: {name}" + (f" -- {detail}" if detail and not ok else ""))


def approx(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


class FakeOverpassClient:
    """GraphService統合検証用。Overpass API形式の生データを返し、呼び出し回数を数える。"""

    def __init__(self):
        self.call_count = 0

    async def get_ways_and_nodes(self, client, bbox):
        self.call_count += 1
        raw_ways = [
            {"id": WAY_A, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [N1, N2, N3]},
            {"id": WAY_B, "tags": {"highway": "residential"}, "nodes": [N4, N2, N5]},
            {"id": WAY_C, "tags": {"highway": "service", "surface": "gravel", "oneway": "yes"}, "nodes": [N3, N6]},
        ]
        return raw_ways, dict(NODE_COORDS)


async def cleanup(engine) -> None:
    """フィクスチャ由来の行をすべて削除する（属性はroad_edgesのON DELETE CASCADEで消える）。"""
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM road_edges WHERE osm_way_id = ANY(:ids)"), {"ids": FIXTURE_WAY_IDS}
        )
        await conn.execute(
            text("DELETE FROM road_nodes WHERE osm_node_id = ANY(:ids)"), {"ids": FIXTURE_NODE_IDS}
        )
        await conn.execute(
            text("DELETE FROM osm_raw_ways WHERE osm_way_id = ANY(:ids)"), {"ids": FIXTURE_WAY_IDS}
        )
        await conn.execute(
            text("DELETE FROM osm_raw_nodes WHERE osm_node_id = ANY(:ids)"), {"ids": FIXTURE_NODE_IDS}
        )
        await conn.execute(
            text("DELETE FROM road_graph_tiles WHERE zoom = :z AND x = :x AND y = :y"),
            {"z": FIXTURE_TILE[0], "x": FIXTURE_TILE[1], "y": FIXTURE_TILE[2]},
        )
        for x, y in tiles_covering_bbox(BBOX, ROAD_GRAPH_TILE_ZOOM):
            await conn.execute(
                text("DELETE FROM road_graph_tiles WHERE zoom = :z AND x = :x AND y = :y"),
                {"z": ROAD_GRAPH_TILE_ZOOM, "x": x, "y": y},
            )


async def main() -> int:
    engine = get_engine()
    session_factory = get_session_factory()

    print("== 0. 接続・スキーマ作成（create_tables冪等性） ==")
    async with engine.connect() as conn:
        version = (await conn.execute(text("SELECT postgis_version()"))).scalar()
    print(f"  postgis_version: {version}")
    await create_tables(engine)  # 既存テーブルがあっても成功すること（IF NOT EXISTS相当）
    await create_tables(engine)  # 2回目も成功すること
    check("create_tablesが既存スキーマに対して冪等", True)
    applied_first = await apply_pending_migrations(engine)
    applied_second = await apply_pending_migrations(engine)  # 2回目は空リスト（適用済みスキップ）
    check("apply_pending_migrationsが冪等（2回目は再適用しない）", applied_second == [])

    await cleanup(engine)  # 前回の失敗残骸があれば除去

    try:
        async with session_factory() as session:
            repo = RoadGraphRepository(session)

            print("== 1. save_raw_ways / get_way_specs_with_closure ==")
            await repo.save_raw_ways(WAY_SPECS, NODE_COORDS)
            await repo.save_raw_ways(WAY_SPECS, NODE_COORDS)  # UPSERT冪等性
            specs, coords, primary_ids = await repo.get_way_specs_with_closure(BBOX)
            by_id = {s.osm_way_id: s for s in specs}
            check("closureが3 Way（主対象A,B＋近傍C）を返す", set(by_id) == {WAY_A, WAY_B, WAY_C},
                  f"got={sorted(by_id)}")
            check("primary_way_idsが{A,B}（bbox外ノードのみのCは主対象でない）",
                  primary_ids == {WAY_A, WAY_B}, f"got={sorted(primary_ids)}")
            check("WaySpecのタグ・direction往復（Cはforward/gravel/service）",
                  by_id.get(WAY_C) is not None
                  and by_id[WAY_C].direction == "forward"
                  and by_id[WAY_C].surface == "gravel"
                  and by_id[WAY_C].highway == "service")
            check("node_ids配列の順序保持", by_id.get(WAY_A) is not None and by_id[WAY_A].node_ids == [N1, N2, N3])
            n1 = coords.get(N1)
            check("ノード座標の(lat,lon)軸順往復",
                  n1 is not None and approx(n1[0], 35.0) and approx(n1[1], 139.0), f"got={n1}")
            check("closureがWay全長分のノード座標を返す（bbox外のN3,N6を含む）",
                  set(coords) == set(FIXTURE_NODE_IDS), f"got={sorted(coords)}")

            print("== 2. build_road_graph → save_graph → get_graph_in_bbox ==")
            graph = build_road_graph(specs, coords)
            # 期待: AはN2(A×B交差)とN3(A×Cノード共有)で分割→2セグメント×双方向=4、
            #       BはN2で分割→4、Cは一方通行1（合計9）。主対象(A,B)のみで8。
            check("交差点分割の結果が期待どおり（全9Edge）", len(graph.edges) == 9, f"got={len(graph.edges)}")
            primary_edges = {eid: e for eid, e in graph.edges.items() if e.osm_way_id in primary_ids}
            referenced = {e.from_node_id for e in primary_edges.values()} | {e.to_node_id for e in primary_edges.values()}
            primary_graph = RoadGraph(
                graph_version=graph.graph_version,
                nodes={nid: n for nid, n in graph.nodes.items() if nid in referenced},
                edges=primary_edges,
            )
            await repo.save_graph(primary_graph, way_ids_to_replace=primary_ids)

            loaded = await repo.get_graph_in_bbox(BBOX)
            check("get_graph_in_bboxが主対象8Edgeを返す（近傍Cの未保存も確認）",
                  loaded is not None and len(loaded.edges) == 8,
                  f"got={len(loaded.edges) if loaded else None}")
            if loaded is not None:
                sample_id = "way-920000000001-seg0-fwd"
                orig, got = primary_graph.edges.get(sample_id), loaded.edges.get(sample_id)
                geom_ok = (
                    orig is not None and got is not None
                    and len(orig.geometry) == len(got.geometry)
                    and all(approx(a[0], b[0]) and approx(a[1], b[1]) for a, b in zip(orig.geometry, got.geometry))
                )
                check("Edgeジオメトリ（LINESTRING）の[lat,lon]往復", geom_ok)
                check("distance_m・FK（from/to node）往復",
                      orig is not None and got is not None
                      and approx(orig.distance_m, got.distance_m, 0.01)
                      and got.from_node_id == orig.from_node_id and got.to_node_id == orig.to_node_id)
                node = loaded.nodes.get(f"osm-node-{N1}")
                check("Node座標の往復（osm-node内部ID・lat/lon軸順）",
                      node is not None and approx(node.latitude, 35.0) and approx(node.longitude, 139.0))

            # delete-then-reinsertの冪等性（再保存してもEdge数が増減しない）
            await repo.save_graph(primary_graph, way_ids_to_replace=primary_ids)
            reloaded = await repo.get_graph_in_bbox(BBOX)
            check("save_graph再実行（delete-then-reinsert）後もEdge数が不変",
                  reloaded is not None and len(reloaded.edges) == 8,
                  f"got={len(reloaded.edges) if reloaded else None}")

            print("== 3. Attribute（surface/elevation）の保存・読込 ==")
            # surfaceは専用テーブルを持たず、road_edges.osm_way_id経由でosm_raw_ways.surfaceを
            # JOIN導出する（改善計画T9）。ステップ1のsave_raw_waysで既に保存済みのため、
            # ここでの保存操作は不要。
            got_surface = await repo.get_surface_attributes(list(primary_edges))
            check("surface_attributesの件数一致（8件）", len(got_surface) == 8, f"got={len(got_surface)}")
            a_edge = "way-920000000001-seg0-fwd"
            check("surfaceのJOIN導出（Aはasphalt）",
                  got_surface.get(a_edge) == "asphalt")

            elev = ElevationAttribute(
                edge_id=a_edge, start_elevation_m=10.0, end_elevation_m=15.5,
                elevation_gain_m=5.5, elevation_loss_m=0.0,
                average_grade=6.11, max_grade=8.0, min_grade=1.2,
                data_source="phase0-verify", data_version="v-test",
                calculated_at=datetime.now(timezone.utc).isoformat(),
            )
            await repo.save_elevation_attributes([elev])
            got_elev = await repo.get_elevation_attributes([a_edge])
            round_trip_ok = (
                a_edge in got_elev
                and got_elev[a_edge].elevation_gain_m == 5.5
                and got_elev[a_edge].data_version == "v-test"
                and datetime.fromisoformat(got_elev[a_edge].calculated_at) == datetime.fromisoformat(elev.calculated_at)
            )
            check("elevation_attributesの往復（timestamptz含む）", round_trip_ok)

            print("== 4. タイル取得済みマーカー ==")
            z, x, y = FIXTURE_TILE
            check("未マークのタイルはis_tile_cached=False", not await repo.is_tile_cached(z, x, y))
            await repo.mark_tile_cached(z, x, y)
            await repo.mark_tile_cached(z, x, y)  # UPSERT冪等性
            check("マーク後はis_tile_cached=True", await repo.is_tile_cached(z, x, y))
            # T6以降、repositoryの書き込みメソッドはcommitしない（呼び出し側が確定する規約）。
            # ブロック内の読み書きは同一セッションで完結するが、ここで確定しないと
            # セッション終了時にロールバックされ、後続の別セッションから見えなくなる。
            await repo.commit()

        print("== 5. GraphService統合（タイルキャッシュのオーケストレーション） ==")
        # 生データ・Edgeを一旦消し、GraphServiceがゼロから構築する流れを検証する
        await cleanup(engine)
        fake_overpass = FakeOverpassClient()
        async with session_factory() as session:
            service = GraphService(fake_overpass, http_client=None, repository=RoadGraphRepository(session))
            result1 = await service.get_or_build_graph_with_attributes(BBOX)
            calls_after_first = fake_overpass.call_count
            expected_tiles = len(tiles_covering_bbox(BBOX, ROAD_GRAPH_TILE_ZOOM))
            check("初回はタイル数分だけOverpass（fake）を呼ぶ",
                  calls_after_first == expected_tiles, f"calls={calls_after_first}, tiles={expected_tiles}")
            check("初回呼び出しが主対象8Edge＋8 surface属性を返す",
                  result1 is not None and len(result1[0].edges) == 8 and len(result1[1]) == 8,
                  f"got={None if result1 is None else (len(result1[0].edges), len(result1[1]))}")
        async with session_factory() as session:
            service = GraphService(fake_overpass, http_client=None, repository=RoadGraphRepository(session))
            result2 = await service.get_or_build_graph_with_attributes(BBOX)
            check("2回目はタイルキャッシュによりOverpass（fake）を一切呼ばない",
                  fake_overpass.call_count == calls_after_first, f"calls={fake_overpass.call_count}")
            check("2回目もDBから同一のグラフを返す",
                  result2 is not None and len(result2[0].edges) == 8
                  and set(result2[0].edges) == set(result1[0].edges))
    finally:
        print("== 後片付け（フィクスチャ行の削除） ==")
        await cleanup(engine)
        await engine.dispose()

    failed = [r for r in _results if not r[1]]
    print()
    print(f"結果: {len(_results) - len(failed)}/{len(_results)} PASS")
    if failed:
        for name, _, detail in failed:
            print(f"  FAIL: {name}" + (f" -- {detail}" if detail else ""))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
