"""RoadGraphRepositoryのPostGIS統合テスト。

ridecompass_test DB(conftest.pyのroad_graph_session/road_graph_repositoryフィクスチャ)への
実接続が必要。接続できない環境ではフィクスチャがpytest.skip()する。
"""

import logging
from datetime import datetime, timezone

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import insert, text

from app.domain.attributes import ElevationAttribute
from app.domain.graph import WaySpec, build_road_graph
from app.domain.region import BoundingBox
from app.infrastructure import accident_models  # noqa: F401  Base.metadataへaccident_*テーブルを登録するためのimport
from app.infrastructure import designation_models  # noqa: F401  Base.metadataへdesignation_*/route_designationsテーブルを登録するためのimport
from app.infrastructure.road_graph_models import EdgeAttributeCountsRow, OsmRawPoiRow

# road_graph_session/road_graph_repository（conftest.py）はDB接続確立コスト削減のため
# ファイル単位で1本のエンジン・イベントループを使い回す設計。ファイル内の全テストの
# イベントループスコープをそれに合わせる必要がある。
# xdist_group="postgis": 改善計画T233フォローアップ。pytest-xdist（-n auto）導入時、
# 同じridecompass_test DBへ接続する全PostGIS統合テストファイルを同一workerへ固定し
# 直列実行させる（別workerで同時にTRUNCATEされるレースを防ぐ。docs/testing.mdパターン2）。
pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.xdist_group(name="postgis")]

NODE1 = (35.700, 139.700)
NODE2 = (35.701, 139.701)
NODE3 = (35.750, 139.750)
NODE4 = (35.751, 139.751)

BBOX_AROUND_NODE1_2 = BoundingBox(
    min_latitude=35.6995, min_longitude=139.6995, max_latitude=35.7015, max_longitude=139.7015
)
BBOX_AROUND_NODE3_4 = BoundingBox(
    min_latitude=35.7495, min_longitude=139.7495, max_latitude=35.7515, max_longitude=139.7515
)
BBOX_FAR_AWAY = BoundingBox(min_latitude=10.0, min_longitude=10.0, max_latitude=10.01, max_longitude=10.01)
# NODE1のみを覆い、NODE2は含まない狭いbbox(closureテストで「bbox内はnode1のみ」を
# 保証するために使う。BBOX_AROUND_NODE1_2はNODE2も含んでしまうため使えない)。
BBOX_AROUND_NODE1_ONLY = BoundingBox(
    min_latitude=35.6995, min_longitude=139.6995, max_latitude=35.7003, max_longitude=139.7003
)


async def test_get_graph_in_bbox_returns_none_when_nothing_saved(road_graph_repository):
    result = await road_graph_repository.get_graph_in_bbox(BBOX_AROUND_NODE1_2)

    assert result is None


async def test_save_graph_and_get_graph_in_bbox_roundtrip(road_graph_repository):
    ways = [WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")]
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph(ways, nodes, graph_version="v1")

    await road_graph_repository.save_graph(graph)
    result = await road_graph_repository.get_graph_in_bbox(BBOX_AROUND_NODE1_2)

    assert result is not None
    assert result.graph_version == "cached"  # DBから読んだ場合は常にCACHED_GRAPH_VERSION
    assert len(result.edges) == 2  # 双方向
    assert len(result.nodes) == 2
    assert {e.osm_way_id for e in result.edges.values()} == {100}


async def test_get_graph_in_bbox_only_returns_edges_intersecting_bbox(road_graph_repository):
    ways = [
        WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential"),
        WaySpec(osm_way_id=200, node_ids=[3, 4], highway="residential"),
    ]
    nodes = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4}
    graph = build_road_graph(ways, nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)

    result_1_2 = await road_graph_repository.get_graph_in_bbox(BBOX_AROUND_NODE1_2)
    result_3_4 = await road_graph_repository.get_graph_in_bbox(BBOX_AROUND_NODE3_4)
    result_far = await road_graph_repository.get_graph_in_bbox(BBOX_FAR_AWAY)

    assert {e.osm_way_id for e in result_1_2.edges.values()} == {100}
    assert {e.osm_way_id for e in result_3_4.edges.values()} == {200}
    assert result_far is None


async def test_get_graph_topology_in_bbox_returns_none_when_nothing_saved(road_graph_repository):
    result = await road_graph_repository.get_graph_topology_in_bbox(BBOX_AROUND_NODE1_2)

    assert result is None


async def test_get_graph_topology_in_bbox_matches_get_graph_in_bbox_coordinates(road_graph_repository):
    # 改善計画T248回帰テスト: get_graph_topology_in_bboxはgeom列を取得せず
    # ST_X/ST_Yで緯度経度を直接計算する（shapely decodeを回避するため）。
    # get_graph_in_bbox（shapely decode経由）と同じ座標値を返すことを確認する。
    ways = [WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")]
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph(ways, nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)

    topology = await road_graph_repository.get_graph_topology_in_bbox(BBOX_AROUND_NODE1_2)
    full = await road_graph_repository.get_graph_in_bbox(BBOX_AROUND_NODE1_2)

    assert topology is not None
    assert topology.graph_version == "cached"
    # 改善計画T248: 戻り値の実体型はPydantic RoadGraphではなく軽量dataclassのLeanRoadGraph
    # （Node.model_construct/DirectedEdge.model_constructのオーバーヘッドを避けるため）。
    from app.domain.graph import LeanEdge, LeanNode, LeanRoadGraph

    assert isinstance(topology, LeanRoadGraph)
    assert all(isinstance(n, LeanNode) for n in topology.nodes.values())
    assert all(isinstance(e, LeanEdge) for e in topology.edges.values())
    assert set(topology.edges.keys()) == set(full.edges.keys())
    assert set(topology.nodes.keys()) == set(full.nodes.keys())
    for node_id, topology_node in topology.nodes.items():
        full_node = full.nodes[node_id]
        assert topology_node.latitude == pytest.approx(full_node.latitude, abs=1e-9)
        assert topology_node.longitude == pytest.approx(full_node.longitude, abs=1e-9)
        assert topology_node.osm_node_id == full_node.osm_node_id
    # 探索フェーズ向けの軽量版はgeometryを持たない（プレースホルダの空リスト）。
    assert all(edge.geometry == [] for edge in topology.edges.values())
    # from/to node・距離・osm_way_id・highway・bearing_degはget_graph_in_bboxと同じ値を持つ。
    for edge_id, topology_edge in topology.edges.items():
        full_edge = full.edges[edge_id]
        assert topology_edge.from_node_id == full_edge.from_node_id
        assert topology_edge.to_node_id == full_edge.to_node_id
        assert topology_edge.distance_m == pytest.approx(full_edge.distance_m)
        assert topology_edge.osm_way_id == full_edge.osm_way_id
        assert topology_edge.highway == full_edge.highway
        assert topology_edge.bearing_deg == pytest.approx(full_edge.bearing_deg)


async def test_get_graph_topology_in_bbox_only_returns_edges_intersecting_bbox(road_graph_repository):
    ways = [
        WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential"),
        WaySpec(osm_way_id=200, node_ids=[3, 4], highway="residential"),
    ]
    nodes = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4}
    graph = build_road_graph(ways, nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)

    result_1_2 = await road_graph_repository.get_graph_topology_in_bbox(BBOX_AROUND_NODE1_2)
    result_far = await road_graph_repository.get_graph_topology_in_bbox(BBOX_FAR_AWAY)

    assert {e.osm_way_id for e in result_1_2.edges.values()} == {100}
    assert result_far is None


async def test_get_edges_with_geometry_returns_hydrated_geometry_for_requested_edges(road_graph_repository):
    # 改善計画T218のhydrate経路（trace_loop/preview_segmentの主経路）の実SQL確認。
    # get_graph_topology_in_bboxで読んだgeometry抜きの探索用グラフから、確定した経路の
    # edge_idだけを渡して実ジオメトリを取得し直す用途。
    ways = [WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")]
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph(ways, nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    topology = await road_graph_repository.get_graph_topology_in_bbox(BBOX_AROUND_NODE1_2)
    edge_id = next(iter(topology.edges))

    hydrated = await road_graph_repository.get_edges_with_geometry([edge_id])

    assert set(hydrated.keys()) == {edge_id}
    edge = hydrated[edge_id]
    # topologyの空プレースホルダとは異なり、実際の形状点列が入る（NODE1→NODE2の2点）。
    assert edge.geometry == [[NODE1[0], NODE1[1]], [NODE2[0], NODE2[1]]]
    assert edge.from_node_id == topology.edges[edge_id].from_node_id
    assert edge.to_node_id == topology.edges[edge_id].to_node_id
    assert edge.distance_m == pytest.approx(topology.edges[edge_id].distance_m)
    assert edge.osm_way_id == 100
    assert edge.highway == "residential"


async def test_get_edges_with_geometry_ignores_edge_ids_not_found(road_graph_repository):
    ways = [WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")]
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph(ways, nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    hydrated = await road_graph_repository.get_edges_with_geometry([edge_id, "does-not-exist"])

    assert set(hydrated.keys()) == {edge_id}


async def test_get_edges_with_geometry_returns_empty_dict_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_edges_with_geometry([]) == {}


async def test_save_graph_upserts_same_edge_without_duplicating(road_graph_repository):
    ways = [WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")]
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph(ways, nodes, graph_version="v1")

    await road_graph_repository.save_graph(graph)
    await road_graph_repository.save_graph(graph)  # 同じ内容を再度保存

    result = await road_graph_repository.get_graph_in_bbox(BBOX_AROUND_NODE1_2)
    assert len(result.edges) == 2  # 増えない(決定論的なedge_idでUPSERT)


async def test_save_graph_with_way_ids_to_replace_deletes_then_reinserts_only_target_way(road_graph_repository):
    # v1: way100([1,2])とway200([3,4])を保存
    ways_v1 = [
        WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential"),
        WaySpec(osm_way_id=200, node_ids=[3, 4], highway="residential"),
    ]
    nodes_v1 = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4}
    graph_v1 = build_road_graph(ways_v1, nodes_v1, graph_version="v1")
    await road_graph_repository.save_graph(graph_v1)

    before = await road_graph_repository.get_graph_in_bbox(BBOX_AROUND_NODE1_2)
    assert len(before.edges) == 2  # way100は1区間(seg0)のみ、双方向で2Edge

    # way100を再取得した結果、node6で新たに交差点として分割されたと仮定(近傍way300が
    # node6を共有)。way_ids_to_replace={100}なので、way300自体のEdgeはこの呼び出しでは
    # 保存されない(道路網の文脈情報としてのみ使う、road_graph_repository.pyのdocstring参照)。
    node6 = (35.7005, 139.7005)
    node7 = (35.699, 139.699)
    ways_v2 = [
        WaySpec(osm_way_id=100, node_ids=[1, 6, 2], highway="residential"),
        WaySpec(osm_way_id=300, node_ids=[6, 7], highway="residential"),
    ]
    nodes_v2 = {1: NODE1, 2: NODE2, 6: node6, 7: node7}
    graph_v2 = build_road_graph(ways_v2, nodes_v2, graph_version="v2")

    await road_graph_repository.save_graph(graph_v2, way_ids_to_replace={100})

    after = await road_graph_repository.get_graph_in_bbox(BBOX_AROUND_NODE1_2)
    way100_edges = {eid: e for eid, e in after.edges.items() if e.osm_way_id == 100}
    way300_edges = {eid: e for eid, e in after.edges.items() if e.osm_way_id == 300}
    assert len(way100_edges) == 4  # node6で2区間に分割、双方向で4Edge(古い1区間分は残らない)
    assert way300_edges == {}  # way_ids_to_replace外なので保存されない

    # way200は今回の呼び出し対象外なので変化しない
    still_there = await road_graph_repository.get_graph_in_bbox(BBOX_AROUND_NODE3_4)
    assert {e.osm_way_id for e in still_there.edges.values()} == {200}


async def test_save_graph_with_way_ids_to_replace_handles_edge_count_beyond_asyncpg_parameter_limit(
    road_graph_repository, road_graph_session,
):
    """改善計画T224の回帰テスト。`new_edge_ids`（再構築対象の全edge_id）を素朴に
    `.not_in(...)`でIN句化すると、要素数が多い場合にasyncpgのプリペアド文パラメータ上限
    （32,767個）を超えて`InterfaceError`になっていた（都心密度のbboxでroad_graphエンジンの
    再構築経路が毎回500エラーになる実障害、統合レビュー2026-08-23で発覚）。
    `=ANY(配列)`化（要素数に関わらず1パラメータで済む設計）に修正済みであることの回帰確認と、
    `way_ids_to_replace`のDELETEが`_ID_CHUNK_SIZE`（10,000）単位でチャンク分割される境界
    （1件ずつのIN句化ではなく複数チャンクにまたがる場合でも正しく全件処理されること）を
    1回のsave_graph呼び出しで両方カバーする。

    改善計画T329: way数はチャンク境界（10,000件）を2回踏破できる最小限（10,050、
    10,000+50の2チャンク）へ削減し、完了確認も`get_graph_in_bbox`によるジオメトリ
    フルデコード（全edgeのWKBをPython側までデコードするコスト）ではなく`road_edges`の
    行数を直接COUNTする軽量クエリへ変更した（元は17,000way/34,000edgeでbackend全体の
    テスト実行時間の81%[42.75秒]を本テスト単体が占めていた）。
    """
    way_count = 10_050  # 各wayが2Edge（双方向）を生成するため、new_edge_idsは20,100件になる
    ways = [
        WaySpec(osm_way_id=1000 + i, node_ids=[1000 + i, 2000 + i], highway="residential")
        for i in range(way_count)
    ]
    # 実際の座標は問わない（PostGISへ実体化できれば十分）。全way共通の2点を使い回す。
    nodes = {1000 + i: NODE1 for i in range(way_count)} | {2000 + i: NODE2 for i in range(way_count)}
    graph = build_road_graph(ways, nodes, graph_version="v1")
    assert len(graph.edges) == way_count * 2

    way_ids = {w.osm_way_id for w in ways}
    await road_graph_repository.save_graph(graph, way_ids_to_replace=way_ids)

    edge_count = await road_graph_session.scalar(
        text("SELECT count(*) FROM road_edges WHERE osm_way_id = ANY(:ids)"), {"ids": list(way_ids)}
    )
    assert edge_count == way_count * 2


async def test_save_raw_ways_and_get_way_specs_with_closure_returns_empty_for_bbox_without_primary_nodes(
    road_graph_repository,
):
    result = await road_graph_repository.get_way_specs_with_closure(BBOX_AROUND_NODE1_2)

    assert result == ([], {}, set())


async def test_get_way_specs_with_closure_includes_neighbor_ways_sharing_a_node(road_graph_repository):
    # way100(主対象、node1がbbox内)はnode2も参照する。way101(近傍)はnode2を共有するが
    # bbox外のnode3にしか無い。way102は無関係(node4/5のみ)で結果に含まれない。
    way_specs = [
        WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential"),
        WaySpec(osm_way_id=101, node_ids=[2, 3], highway="residential"),
        WaySpec(osm_way_id=102, node_ids=[4, 5], highway="residential"),
    ]
    node_coords = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4, 5: (35.8, 139.8)}
    await road_graph_repository.save_raw_ways(way_specs, node_coords)

    way_specs_out, node_coords_out, primary_way_ids = await road_graph_repository.get_way_specs_with_closure(
        BBOX_AROUND_NODE1_ONLY
    )

    assert primary_way_ids == {100}
    assert {w.osm_way_id for w in way_specs_out} == {100, 101}
    assert set(node_coords_out.keys()) == {1, 2, 3}


async def test_get_way_specs_with_closure_clamps_extent_of_a_long_primary_way(road_graph_repository, caplog):
    """改善計画T69の回帰テスト: bboxをかすめる1本の長大way(河川沿いサイクリングロード等)が
    あると、以前は主対象Way全体のextentがその全長へ広がり、そこに交差する遠方の無関係な
    wayまで近傍として読み込んでいた。extentは要求bboxをNEIGHBOR_EXTENT_MAX_MARGIN_M(10km)
    分だけ拡張した範囲へクランプされ、far_wayは近傍として含まれないことを確認する。
    """
    far_node = (35.700, 140.200)  # node1から経度0.5度(緯度35.7度で約45km)離れた点
    beyond_far_node = (35.700, 140.201)
    way_specs = [
        WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential"),
        # 長大way: node1(bbox内)からfar_nodeまで伸びる(主対象Wayとしてbboxと交差する)。
        WaySpec(osm_way_id=200, node_ids=[1, 98], highway="trunk"),
        # far_node付近だけに存在する無関係way(クランプ無しではextentに含まれてしまう)。
        WaySpec(osm_way_id=300, node_ids=[98, 99], highway="residential"),
    ]
    node_coords = {1: NODE1, 2: NODE2, 98: far_node, 99: beyond_far_node}
    await road_graph_repository.save_raw_ways(way_specs, node_coords)

    with caplog.at_level(logging.WARNING, logger="app.infrastructure.road_graph_repository"):
        way_specs_out, _, primary_way_ids = await road_graph_repository.get_way_specs_with_closure(
            BBOX_AROUND_NODE1_2
        )

    assert primary_way_ids == {100, 200}
    assert {w.osm_way_id for w in way_specs_out} == {100, 200}
    assert any("クランプ" in r.message for r in caplog.records)


async def test_save_raw_ways_is_idempotent_upsert(road_graph_repository):
    way_specs = [WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")]
    node_coords = {1: NODE1, 2: NODE2}

    await road_graph_repository.save_raw_ways(way_specs, node_coords)
    await road_graph_repository.save_raw_ways(way_specs, node_coords)  # 同じ内容を再保存

    way_specs_out, _, primary_way_ids = await road_graph_repository.get_way_specs_with_closure(BBOX_AROUND_NODE1_2)
    assert len(way_specs_out) == 1
    assert primary_way_ids == {100}


async def test_save_raw_ways_with_empty_list_is_a_noop(road_graph_repository):
    await road_graph_repository.save_raw_ways([], {})

    result = await road_graph_repository.get_way_specs_with_closure(BBOX_AROUND_NODE1_2)
    assert result == ([], {}, set())


async def test_is_split_up_to_date_returns_true_when_no_ways_in_bbox(road_graph_repository):
    assert await road_graph_repository.is_split_up_to_date(BBOX_AROUND_NODE1_2) is True


async def test_is_split_up_to_date_returns_false_for_way_saved_raw_but_never_split(road_graph_repository):
    # 通常の初回リクエスト相当: 生データは取得済みだが、まだsave_graphでsplitされていない。
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})

    assert await road_graph_repository.is_split_up_to_date(BBOX_AROUND_NODE1_2) is False


async def test_is_split_up_to_date_returns_true_after_save_raw_ways_and_save_graph(road_graph_repository):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph, way_ids_to_replace={100})

    assert await road_graph_repository.is_split_up_to_date(BBOX_AROUND_NODE1_2) is True


async def test_is_split_up_to_date_returns_false_after_way_content_changes_without_resplitting(
    road_graph_repository,
):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential", surface="asphalt")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph, way_ids_to_replace={100})
    assert await road_graph_repository.is_split_up_to_date(BBOX_AROUND_NODE1_2) is True

    changed_way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential", surface="gravel")
    await road_graph_repository.save_raw_ways([changed_way], nodes)  # save_graphは呼ばない

    assert await road_graph_repository.is_split_up_to_date(BBOX_AROUND_NODE1_2) is False


async def test_is_split_up_to_date_stays_true_after_semantically_identical_resave(road_graph_repository):
    """Finding Aの回帰テスト: 内容が完全に同一なWayの再保存はupdated_atを進めない
    （_bulk_upsertのON CONFLICT ... DO UPDATE ... WHERE句が実際に機能していることの確認）。
    隣接タイルの取得でOverpassが同じWayを再送するケースを模す。
    """
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential", surface="asphalt")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph, way_ids_to_replace={100})
    assert await road_graph_repository.is_split_up_to_date(BBOX_AROUND_NODE1_2) is True

    # 内容が完全に同一なWayを再保存
    identical_way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential", surface="asphalt")
    await road_graph_repository.save_raw_ways([identical_way], nodes)

    assert await road_graph_repository.is_split_up_to_date(BBOX_AROUND_NODE1_2) is True


async def test_is_split_up_to_date_true_again_after_resave_reflects_new_split(road_graph_repository):
    # stale -> save_graph -> 再度fresh、という自己修復ラウンドトリップ。
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential", surface="asphalt")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph, way_ids_to_replace={100})

    changed_way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential", surface="gravel")
    await road_graph_repository.save_raw_ways([changed_way], nodes)
    assert await road_graph_repository.is_split_up_to_date(BBOX_AROUND_NODE1_2) is False

    graph_v2 = build_road_graph([changed_way], nodes, graph_version="v2")
    await road_graph_repository.save_graph(graph_v2, way_ids_to_replace={100})

    assert await road_graph_repository.is_split_up_to_date(BBOX_AROUND_NODE1_2) is True


async def test_save_graph_stamps_split_at_only_for_way_ids_to_replace(road_graph_repository):
    ways = [
        WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential"),
        WaySpec(osm_way_id=200, node_ids=[3, 4], highway="residential"),
    ]
    nodes = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4}
    await road_graph_repository.save_raw_ways(ways, nodes)
    graph = build_road_graph(ways, nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph, way_ids_to_replace={100, 200})
    assert await road_graph_repository.is_split_up_to_date(BBOX_AROUND_NODE3_4) is True

    # way100だけを再split（way200には触れない）
    await road_graph_repository.save_graph(graph, way_ids_to_replace={100})

    # way200の生データを変更する。split_atが更新されていなければ（＝100だけの
    # save_graph呼び出しでway200のsplit_atが誤って進んでいなければ）staleになるはず。
    changed_way200 = WaySpec(osm_way_id=200, node_ids=[3, 4], highway="residential", surface="gravel")
    await road_graph_repository.save_raw_ways([changed_way200], nodes)

    assert await road_graph_repository.is_split_up_to_date(BBOX_AROUND_NODE3_4) is False


async def test_is_split_up_to_date_true_for_way_that_produces_zero_edges_after_split(road_graph_repository):
    """Finding Bの回帰テスト: 座標既知ノードが2点未満のセグメントしか生成しないWay
    （road_edgesに1件も行が無い）でも、save_graphがsplit_atをスタンプしていれば
    is_split_up_to_dateはFalseに固定されない。

    way100([1,5,2])は、way101がnode5を共有するためnode5が交差点分割点になり、
    [1,5]と[5,2]の2セグメントに割れる。node5の座標は未知のため、どちらのセグメントも
    既知座標1点のみとなりEdge化されない（domain/graph.py参照）。ただしway100自体の
    geomは既知の1・2番ノード2点から実体化されるため「主対象Way」の対象にはなる。
    """
    way100 = WaySpec(osm_way_id=100, node_ids=[1, 5, 2], highway="residential")
    way101 = WaySpec(osm_way_id=101, node_ids=[5, 6], highway="residential")
    nodes = {1: NODE1, 2: NODE2}  # node5, node6は座標未知
    await road_graph_repository.save_raw_ways([way100, way101], nodes)

    graph = build_road_graph([way100, way101], nodes, graph_version="v1")
    way100_edges = {eid: e for eid, e in graph.edges.items() if e.osm_way_id == 100}
    assert way100_edges == {}  # 前提の確認: 本当に0 Edge

    await road_graph_repository.save_graph(graph, way_ids_to_replace={100})

    assert await road_graph_repository.is_split_up_to_date(BBOX_AROUND_NODE1_2) is True


async def test_get_elevation_attributes_returns_empty_dict_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_elevation_attributes([]) == {}


async def test_save_elevation_attributes_with_empty_list_is_a_noop(road_graph_repository):
    await road_graph_repository.save_elevation_attributes([])  # 例外を投げない


async def test_elevation_attributes_roundtrip(road_graph_repository):
    ways = [WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")]
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph(ways, nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    attribute = ElevationAttribute(
        edge_id=edge_id,
        start_elevation_m=10.0,
        end_elevation_m=15.5,
        elevation_gain_m=5.5,
        elevation_loss_m=0.0,
        average_grade=1.2,
        max_grade=1.2,
        min_grade=1.2,
        data_source="gsi",
        data_version="v1",
        calculated_at=datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
    )
    await road_graph_repository.save_elevation_attributes([attribute])

    result = await road_graph_repository.get_elevation_attributes([edge_id, "nonexistent-edge"])

    assert set(result.keys()) == {edge_id}
    assert result[edge_id].start_elevation_m == 10.0
    assert result[edge_id].elevation_gain_m == 5.5
    assert result[edge_id].data_source == "gsi"


async def test_elevation_attributes_upsert_overwrites_previous_value(road_graph_repository):
    ways = [WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")]
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph(ways, nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))
    now_iso = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()

    await road_graph_repository.save_elevation_attributes(
        [ElevationAttribute(edge_id=edge_id, start_elevation_m=10.0, data_source="gsi", calculated_at=now_iso)]
    )
    await road_graph_repository.save_elevation_attributes(
        [ElevationAttribute(edge_id=edge_id, start_elevation_m=99.0, data_source="gsi", calculated_at=now_iso)]
    )

    result = await road_graph_repository.get_elevation_attributes([edge_id])
    assert result[edge_id].start_elevation_m == 99.0


async def test_get_surface_attributes_returns_empty_dict_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_surface_attributes([]) == {}


async def test_get_surface_attributes_joins_via_osm_way_id(road_graph_repository):
    """改善計画T9: surfaceは専用テーブルを持たず、road_edges.osm_way_id経由で
    osm_raw_ways.surfaceをJOIN導出する。"""
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential", surface="asphalt")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    result = await road_graph_repository.get_surface_attributes([edge_id, "nonexistent-edge"])

    assert set(result.keys()) == {edge_id}
    assert result[edge_id] == "asphalt"


async def test_get_surface_attributes_is_none_when_raw_way_not_found(road_graph_repository):
    """road_edges.osm_way_idに対応するosm_raw_ways行が無い場合（LEFT JOINで不一致）はNone。"""
    ways = [WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")]
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph(ways, nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)  # save_raw_waysを呼ばない＝osm_raw_ways側は空
    edge_id = next(iter(graph.edges))

    result = await road_graph_repository.get_surface_attributes([edge_id])

    assert result[edge_id] is None


async def test_get_nearest_surface_tags_returns_empty_list_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_nearest_surface_tags([]) == []


async def test_get_nearest_surface_tags_matches_nearby_edge_and_returns_its_surface(road_graph_repository):
    """改善計画T21: openrouteserviceエンジンのサンプル点を自前DBのEdgeへ空間マッチする経路。"""
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential", surface="asphalt")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)

    result = await road_graph_repository.get_nearest_surface_tags([NODE1], max_distance_m=30.0)

    assert result == ["asphalt"]


async def test_get_nearest_surface_tags_returns_none_beyond_max_distance_m(road_graph_repository):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential", surface="asphalt")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)

    result = await road_graph_repository.get_nearest_surface_tags([(35.9, 140.0)], max_distance_m=30.0)

    assert result == [None]


async def test_get_nearest_surface_tags_preserves_input_order_for_multiple_points(road_graph_repository):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential", surface="gravel")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)

    result = await road_graph_repository.get_nearest_surface_tags(
        [(35.9, 140.0), NODE1, NODE2, (35.9, 140.0)], max_distance_m=30.0
    )

    assert result == [None, "gravel", "gravel", None]


# --- 静的道路属性P1（信号・横断歩道・一時停止・踏切のnode取込・停止密度評価） ---
# osm_raw_poisへの書き込みメソッドはRoadGraphRepositoryに無い（PBF取込バッチが直接asyncpg
# COPYで書くため、ADR決定によりOverpassフォールバック側にも実装していない）。統合テストでは
# セッションへ直接INSERTしてテストデータを用意する。


async def _insert_poi(session, osm_node_id: int, kind: str, lat: float, lon: float) -> None:
    await session.execute(
        text(
            "INSERT INTO osm_raw_pois (osm_node_id, kind, tags, geom, updated_at) "
            "VALUES (:id, :kind, '{}'::jsonb, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), now())"
        ),
        {"id": osm_node_id, "kind": kind, "lat": lat, "lon": lon},
    )


async def test_get_stop_poi_counts_returns_empty_dict_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_stop_poi_counts([]) == {}


async def test_get_stop_poi_counts_counts_nearby_pois(road_graph_repository, road_graph_session):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    await _insert_poi(road_graph_session, 900, "traffic_signals", *NODE1)
    await _insert_poi(road_graph_session, 901, "crossing", *NODE2)
    await road_graph_session.commit()

    result = await road_graph_repository.get_stop_poi_counts([edge_id], max_distance_m=30.0)

    assert result[edge_id] == 2


async def test_get_stop_poi_counts_edge_with_no_nearby_pois_is_zero_not_missing(road_graph_repository):
    """該当POIが0件でもedge_id自体はNoneではなく0として結果に含まれる
    （EvaluationServiceが「データ無し(None)」と「0件」を区別する前提）。"""
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    result = await road_graph_repository.get_stop_poi_counts([edge_id])

    assert result == {edge_id: 0}


async def test_get_stop_poi_counts_ignores_pois_beyond_max_distance_m(road_graph_repository, road_graph_session):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    await _insert_poi(road_graph_session, 900, "traffic_signals", *NODE3)  # 遠方
    await road_graph_session.commit()

    result = await road_graph_repository.get_stop_poi_counts([edge_id], max_distance_m=30.0)

    assert result[edge_id] == 0


async def test_get_stop_poi_counts_excludes_supply_poi_kinds(road_graph_repository, road_graph_session):
    """改善計画T145b実装中に発見したバグの回帰テスト: T101で補給POI（convenience/
    vending_machine等）が同じosm_raw_poisテーブルへ入って以降、kindを絞らないCOUNTは
    停止密度へコンビニ・自販機を誤算入していた。STOP_POI_KINDS該当のみ数えることを確認する。"""
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    await _insert_poi(road_graph_session, 900, "traffic_signals", *NODE1)
    await _insert_poi(road_graph_session, 901, "convenience", *NODE1)
    await _insert_poi(road_graph_session, 902, "vending_machine", *NODE2)
    await road_graph_session.commit()

    result = await road_graph_repository.get_stop_poi_counts([edge_id], max_distance_m=30.0)

    assert result[edge_id] == 1


async def test_get_nearest_stop_poi_counts_excludes_supply_poi_kinds(road_graph_repository, road_graph_session):
    """get_stop_poi_countsと対称のkindフィルタ回帰テスト（ORSエンジン経路）。"""
    await _insert_poi(road_graph_session, 900, "stop", *NODE1)
    await _insert_poi(road_graph_session, 901, "toilets", *NODE1)
    await road_graph_session.commit()

    result = await road_graph_repository.get_nearest_stop_poi_counts([NODE1], max_distance_m=30.0)

    assert result == [1]


async def test_get_nearest_stop_poi_counts_returns_empty_list_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_nearest_stop_poi_counts([]) == []


async def test_get_nearest_stop_poi_counts_counts_pois_near_each_point(road_graph_repository, road_graph_session):
    await _insert_poi(road_graph_session, 900, "stop", *NODE1)
    await _insert_poi(road_graph_session, 901, "give_way", *NODE1)
    await road_graph_session.commit()

    result = await road_graph_repository.get_nearest_stop_poi_counts(
        [NODE1, NODE3], max_distance_m=30.0
    )

    assert result == [2, 0]


# --- 静的道路属性P1残り（車ストレス・自転車インフラ・交差点密度の評価組み込み） ---


async def test_get_way_tags_returns_empty_dict_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_way_tags([]) == {}


async def test_get_way_tags_joins_via_osm_way_id(road_graph_repository):
    way = WaySpec(
        osm_way_id=100, node_ids=[1, 2], highway="residential", tags={"lanes": "2", "maxspeed": "40"}
    )
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    result = await road_graph_repository.get_way_tags([edge_id, "nonexistent-edge"])

    assert set(result.keys()) == {edge_id}
    assert result[edge_id] == {"lanes": "2", "maxspeed": "40"}


async def test_get_way_tags_is_empty_dict_when_raw_way_not_found(road_graph_repository):
    """road_edges.osm_way_idに対応するosm_raw_ways行が無い場合（LEFT JOINで不一致）は`{}`
    （get_surface_attributesのNoneとは違い、taglessと同じ扱いにする。domain/evaluation.py:
    compute_edge_costのway_tagsコメント参照）。"""
    ways = [WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")]
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph(ways, nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)  # save_raw_waysを呼ばない＝osm_raw_ways側は空
    edge_id = next(iter(graph.edges))

    result = await road_graph_repository.get_way_tags([edge_id])

    assert result[edge_id] == {}


async def test_get_way_tags_by_osm_way_id_returns_highway_tags_and_is_designated(
    road_graph_repository, road_graph_session
):
    """改善計画T90: 区間クリック時の車ストレス内訳表示。get_nearest_way_tagsの空間マッチ
    （交差点付近で別の道路を拾いうる、実機確認で判明）を避け、osm_way_id完全一致で引く。"""
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="primary", tags={"maxspeed": "60"})
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    await _insert_designation_attribute(road_graph_session, 100, "critical_logistics")
    await road_graph_session.commit()

    result = await road_graph_repository.get_way_tags_by_osm_way_id(100)

    assert result == ("primary", {"maxspeed": "60"}, True)


async def test_get_way_tags_by_osm_way_id_returns_none_when_way_not_found(road_graph_repository):
    assert await road_graph_repository.get_way_tags_by_osm_way_id(999) is None


async def test_get_way_attribute_counts_returns_row_when_present(road_graph_repository, road_graph_session):
    """区間インスペクタ（改善計画T146）。way_attribute_counts（T145b事前集計）に該当行が
    あれば(length_m, accident_count, stop_count, intersection_count)を返す。"""
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    await road_graph_session.execute(
        text(
            "INSERT INTO way_attribute_counts (osm_way_id, length_m, accident_count, stop_count, "
            "intersection_count, computed_at) VALUES (100, 500.0, 1.5, 2, 3, now())"
        )
    )
    await road_graph_session.commit()

    result = await road_graph_repository.get_way_attribute_counts(100)

    assert result == (500.0, 1.5, 2, 3)


async def test_get_way_attribute_counts_returns_none_when_row_missing(road_graph_repository, road_graph_session):
    """該当wayがosm_raw_waysに存在しても、way_attribute_countsバッチ未実行/対象外
    （highway無し等）なら行が無くNone（0件と区別、呼び出し元は算出不能として扱う）。"""
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    await road_graph_session.commit()

    assert await road_graph_repository.get_way_attribute_counts(100) is None


async def test_get_nearest_way_tags_returns_empty_list_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_nearest_way_tags([]) == []


async def test_get_nearest_way_tags_matches_nearby_edge_and_returns_highway_and_tags(road_graph_repository):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="primary", tags={"maxspeed": "60"})
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)

    result = await road_graph_repository.get_nearest_way_tags([NODE1], max_distance_m=30.0)

    assert result == [("primary", {"maxspeed": "60"}, False)]


async def test_get_nearest_way_tags_returns_none_highway_and_empty_tags_beyond_max_distance_m(road_graph_repository):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="primary", tags={"maxspeed": "60"})
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)

    result = await road_graph_repository.get_nearest_way_tags([(35.9, 140.0)], max_distance_m=30.0)

    assert result == [(None, {}, False)]


async def test_get_intersection_counts_returns_empty_dict_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_intersection_counts([]) == {}


async def test_get_intersection_counts_counts_degree_3_node_as_intersection(road_graph_repository):
    """NODE2を3本のWayが共有する（次数3）ため交差点として数えられ、そこへ接続する
    全Edgeが1件を報告する（NODE2自体がEdgeの端点＝距離0のため常にmax_distance_m以内）。
    NODE1・NODE3・NODE4は行き止まり（次数1）のため交差点ではない。"""
    way_a = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    way_b = WaySpec(osm_way_id=101, node_ids=[2, 3], highway="residential")
    way_c = WaySpec(osm_way_id=102, node_ids=[2, 4], highway="residential")
    nodes = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4}
    graph = build_road_graph([way_a, way_b, way_c], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    await road_graph_repository.recompute_node_degrees()
    edge_ids = list(graph.edges.keys())

    result = await road_graph_repository.get_intersection_counts(edge_ids, max_distance_m=30.0)

    assert set(result.keys()) == set(edge_ids)
    assert all(count == 1 for count in result.values())


async def test_get_intersection_counts_degree_2_pass_through_node_is_not_an_intersection(road_graph_repository):
    """NODE2を2本のWayが共有するだけ（次数2、単純な通過点）では交差点扱いにならない。"""
    way_a = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    way_b = WaySpec(osm_way_id=101, node_ids=[2, 3], highway="residential")
    nodes = {1: NODE1, 2: NODE2, 3: NODE3}
    graph = build_road_graph([way_a, way_b], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    await road_graph_repository.recompute_node_degrees()
    edge_ids = list(graph.edges.keys())

    result = await road_graph_repository.get_intersection_counts(edge_ids, max_distance_m=30.0)

    assert all(count == 0 for count in result.values())


async def test_get_intersection_counts_edge_far_from_any_intersection_is_zero(road_graph_repository):
    way_a = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    way_b = WaySpec(osm_way_id=101, node_ids=[2, 3], highway="residential")
    way_c = WaySpec(osm_way_id=102, node_ids=[2, 4], highway="residential")
    # NODE1/2/3/4のクラスタとは無関係な独立したWay（次数3の交差点から遠い）。
    way_isolated = WaySpec(osm_way_id=200, node_ids=[5, 6], highway="residential")
    nodes = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4, 5: (35.600, 139.600), 6: (35.601, 139.601)}
    graph = build_road_graph([way_a, way_b, way_c, way_isolated], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    await road_graph_repository.recompute_node_degrees()
    isolated_edge_ids = [
        edge_id for edge_id, edge in graph.edges.items() if edge.osm_way_id == 200
    ]

    result = await road_graph_repository.get_intersection_counts(isolated_edge_ids, max_distance_m=30.0)

    assert all(count == 0 for count in result.values())


async def test_get_intersection_counts_is_independent_of_edge_id_order_and_subset(road_graph_repository):
    """改善計画T151の回帰テスト: 修正前はget_intersection_counts内部の50,000件チャンク分割が
    入力順序でチャンク境界を決め、同一edge_id集合でも順序が異なると境界をまたぐノードの
    次数が変わりえた。次数をroad_nodes.degree（DB全体の事前集計）へ一本化した後は、
    (1)同一集合を異なる順序で渡しても結果が一致し、(2)集合の一部だけを渡しても
    （呼び出し元の集合から独立してグローバルな次数を参照するため）残りの edge の結果が
    変わらないことを確認する。"""
    way_a = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    way_b = WaySpec(osm_way_id=101, node_ids=[2, 3], highway="residential")
    way_c = WaySpec(osm_way_id=102, node_ids=[2, 4], highway="residential")
    nodes = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4}
    graph = build_road_graph([way_a, way_b, way_c], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    await road_graph_repository.recompute_node_degrees()
    edge_ids = list(graph.edges.keys())

    forward = await road_graph_repository.get_intersection_counts(edge_ids, max_distance_m=30.0)
    reversed_result = await road_graph_repository.get_intersection_counts(
        list(reversed(edge_ids)), max_distance_m=30.0
    )
    assert forward == reversed_result

    # NODE2に接続する3本のうち1本だけを渡しても、NODE2自体の次数（＝グローバルな事実）は
    # 変わらないため、その1本の結果は全件渡したときと同じになるはず。
    single_edge_id = edge_ids[:1]
    partial_result = await road_graph_repository.get_intersection_counts(single_edge_id, max_distance_m=30.0)
    assert partial_result[single_edge_id[0]] == forward[single_edge_id[0]]


async def test_get_nearest_intersection_counts_returns_empty_list_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_nearest_intersection_counts([]) == []


async def test_get_nearest_intersection_counts_counts_intersections_near_each_point(road_graph_repository):
    way_a = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    way_b = WaySpec(osm_way_id=101, node_ids=[2, 3], highway="residential")
    way_c = WaySpec(osm_way_id=102, node_ids=[2, 4], highway="residential")
    nodes = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4}
    graph = build_road_graph([way_a, way_b, way_c], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    await road_graph_repository.recompute_node_degrees()

    result = await road_graph_repository.get_nearest_intersection_counts(
        [NODE2, NODE1], max_distance_m=30.0
    )

    assert result == [1, 0]


# --- 外部静的データソース T50残作業（事故密度の評価組み込み、8軸目） ---
# accident_pointsへの書き込みメソッドはRoadGraphRepositoryに無い（import_accidents.pyが
# 直接asyncpg COPYで書くため）。統合テストではセッションへ直接INSERTしてテストデータを用意する
# （test_accident_repository.py: _insert_accidentと同じパターン）。


async def _insert_accident(
    session, accident_id: str, kind_year: int, lat: float, lon: float, *, involves_bicycle: bool = False, fatal: bool = False
) -> None:
    await session.execute(
        text(
            "INSERT INTO accident_points (accident_id, occurred_year, fatal, involves_bicycle, attrs, geom, updated_at) "
            "VALUES (:id, :year, :fatal, :bicycle, '{}'::jsonb, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), now())"
        ),
        {"id": accident_id, "year": kind_year, "fatal": fatal, "bicycle": involves_bicycle, "lat": lat, "lon": lon},
    )


async def _insert_accident_import_run(session, occurred_year: int, status: str = "succeeded") -> None:
    await session.execute(
        text(
            "INSERT INTO accident_import_runs (occurred_year, file_name, status, started_at) "
            "VALUES (:year, :file_name, :status, now())"
        ),
        {"year": occurred_year, "file_name": f"honhyo_{occurred_year}.csv", "status": status},
    )


async def test_get_accident_counts_returns_empty_dict_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_accident_counts([]) == {}


async def test_get_accident_counts_counts_nearby_accidents(road_graph_repository, road_graph_session):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    await _insert_accident(road_graph_session, "2023-1", 2023, *NODE1, involves_bicycle=True)
    await _insert_accident(road_graph_session, "2023-2", 2023, *NODE2, involves_bicycle=False)
    await road_graph_session.commit()

    # bicycle_only既定値はTrue（改善計画: 事故密度の精度改善）だが、この検証観点は
    # 距離ベースのカウント自体（bicycle_onlyフィルタは下のtest_..._bicycle_only_...で
    # 別途検証する）のため、ここではFalseを明示して両方カウントさせる。
    result = await road_graph_repository.get_accident_counts([edge_id], bicycle_only=False, max_distance_m=30.0)

    assert result[edge_id] == 2


async def test_get_accident_counts_bicycle_only_filters_to_bicycle_related(road_graph_repository, road_graph_session):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    await _insert_accident(road_graph_session, "2023-1", 2023, *NODE1, involves_bicycle=True)
    await _insert_accident(road_graph_session, "2023-2", 2023, *NODE2, involves_bicycle=False)
    await road_graph_session.commit()

    result = await road_graph_repository.get_accident_counts([edge_id], bicycle_only=True, max_distance_m=30.0)

    assert result[edge_id] == 1


async def test_get_accident_counts_weights_fatal_accidents(road_graph_repository, road_graph_session):
    """死亡事故は`ACCIDENT_FATAL_WEIGHT`（3.0）件分として積算される
    （改善計画: 事故密度の精度改善）。1件の非死亡事故＋1件の死亡事故で1+3.0=4.0になることを
    確認する。CASE式でLEFT JOIN不一致行（NULL）を誤って1件と数える回帰
    （実装時に自己発見したバグ）の検知も兼ねる。
    """
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    await _insert_accident(road_graph_session, "2023-1", 2023, *NODE1, fatal=False)
    await _insert_accident(road_graph_session, "2023-2", 2023, *NODE1, fatal=True)
    await road_graph_session.commit()

    result = await road_graph_repository.get_accident_counts([edge_id], bicycle_only=False, max_distance_m=30.0)

    assert result[edge_id] == 4.0


async def test_get_accident_counts_edge_with_no_nearby_accidents_is_zero_not_missing(road_graph_repository):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    result = await road_graph_repository.get_accident_counts([edge_id])

    assert result == {edge_id: 0}


async def test_get_accident_counts_ignores_accidents_beyond_max_distance_m(road_graph_repository, road_graph_session):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    await _insert_accident(road_graph_session, "2023-far", 2023, *NODE3)  # 遠方
    await road_graph_session.commit()

    result = await road_graph_repository.get_accident_counts([edge_id], max_distance_m=30.0)

    assert result[edge_id] == 0


async def test_get_nearest_accident_counts_returns_empty_list_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_nearest_accident_counts([]) == []


async def test_get_nearest_accident_counts_counts_accidents_near_each_point(road_graph_repository, road_graph_session):
    await _insert_accident(road_graph_session, "2023-1", 2023, *NODE1)
    await _insert_accident(road_graph_session, "2023-2", 2023, *NODE1)
    await road_graph_session.commit()

    # bicycle_only既定値はTrue（改善計画: 事故密度の精度改善）。ここでの検証観点は距離ベースの
    # カウント自体（_insert_accidentは既定でinvolves_bicycle=False）のためFalseを明示する。
    result = await road_graph_repository.get_nearest_accident_counts(
        [NODE1, NODE3], bicycle_only=False, max_distance_m=30.0
    )

    assert result == [2, 0]


async def test_get_accident_years_covered_counts_distinct_succeeded_years(road_graph_repository, road_graph_session):
    await _insert_accident_import_run(road_graph_session, 2022)
    await _insert_accident_import_run(road_graph_session, 2023)
    await _insert_accident_import_run(road_graph_session, 2024)
    await _insert_accident_import_run(road_graph_session, 2021, status="failed")  # 失敗runは数えない
    await road_graph_session.commit()

    assert await road_graph_repository.get_accident_years_covered() == 3


async def test_get_accident_years_covered_is_zero_when_no_runs(road_graph_repository):
    assert await road_graph_repository.get_accident_years_covered() == 0


# --- 指定路線コンフレーション機構（外部静的データソース T51） ---
# designation_attributesへの書き込みメソッドはRoadGraphRepositoryに無い
# （match_designations.pyが直接asyncpgで書くため）。統合テストではセッションへ
# 直接INSERTしてテストデータを用意する（_insert_accidentと同じパターン）。
#
# 改善計画T74: designation_attributesはosm_way_id基準（osm_raw_ways FK）のため、
# FK制約を満たすためsave_raw_waysでosm_raw_ways行を用意してからINSERTする。


async def _insert_designation_attribute(session, osm_way_id: int, kind: str, matched_ratio: float = 0.8) -> None:
    await session.execute(
        text(
            "INSERT INTO designation_attributes (osm_way_id, kind, matched_ratio, data_version, calculated_at) "
            "VALUES (:osm_way_id, :kind, :ratio, 'test', now())"
        ),
        {"osm_way_id": osm_way_id, "kind": kind, "ratio": matched_ratio},
    )


async def test_save_graph_resplit_does_not_affect_designation_attributes(
    road_graph_repository, road_graph_session
):
    """改善計画T74の回帰テスト: designation_attributesはosm_way_id基準（osm_raw_ways FK）に
    変更したため、road_edgesの再split（edge_idの変化、旧T66の懸念対象）では一切影響を
    受けない。way構成が変わりsegment数（＝edge_id集合）が変化しても、同じosm_way_idである
    限りget_designated_edge_idsは新edge_idに対して引き続きマッチする。

    v1: 近傍way300がnode6を共有するためway100はnode6で[1,6]/[6,2]の2segmentに分割される。
    v2: way300を含めずway100単独で再取得（node6はもう交差点ではない）ため、
    way100は[1,2]の1segmentへ戻る（segment数が4→2エッジへ変化＝実際に再split発生の証明）。
    """
    node6 = (35.7005, 139.7005)
    node7 = (35.699, 139.699)
    way100 = WaySpec(osm_way_id=100, node_ids=[1, 6, 2], highway="residential")
    way300 = WaySpec(osm_way_id=300, node_ids=[6, 7], highway="residential")
    nodes_v1 = {1: NODE1, 2: NODE2, 6: node6, 7: node7}
    await road_graph_repository.save_raw_ways([way100, way300], nodes_v1)
    graph_v1 = build_road_graph([way100, way300], nodes_v1, graph_version="v1")
    await road_graph_repository.save_graph(graph_v1, way_ids_to_replace={100})
    way100_edges_v1 = sorted(eid for eid in graph_v1.edges if eid.startswith("way-100-"))
    assert len(way100_edges_v1) == 4  # [1,6]/[6,2]の2segment、双方向で4Edge（前提確認）

    await _insert_designation_attribute(road_graph_session, 100, "emergency_transport")
    await road_graph_session.commit()

    # way300を含めずway100単独で再split（node6はもう交差点として扱われない）。
    way100_alone = WaySpec(osm_way_id=100, node_ids=[1, 6, 2], highway="residential")
    nodes_v2 = {1: NODE1, 2: NODE2, 6: node6}
    graph_v2 = build_road_graph([way100_alone], nodes_v2, graph_version="v2")
    new_edge_ids = list(graph_v2.edges.keys())
    assert len(new_edge_ids) == 2  # [1,2]の1segment、双方向で2Edge（実際に再split発生の確認）

    await road_graph_repository.save_graph(graph_v2, way_ids_to_replace={100})

    # osm_way_id=100自体は変わっていないため、再split後の新edge_id全件がdesignatedと判定される。
    assert await road_graph_repository.get_designated_edge_ids(new_edge_ids) == set(new_edge_ids)


async def test_get_designated_edge_ids_returns_empty_set_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_designated_edge_ids([]) == set()


async def test_get_designated_edge_ids_returns_matching_edges(road_graph_repository, road_graph_session):
    way_a = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    way_b = WaySpec(osm_way_id=101, node_ids=[3, 4], highway="residential")
    nodes = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4}
    await road_graph_repository.save_raw_ways([way_a, way_b], nodes)
    graph = build_road_graph([way_a, way_b], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_ids = list(graph.edges.keys())
    designated_edge_id = next(e for e in edge_ids if e.startswith("way-100-"))
    other_edge_id = next(e for e in edge_ids if e.startswith("way-101-"))

    await _insert_designation_attribute(road_graph_session, 100, "emergency_transport")
    await road_graph_session.commit()

    result = await road_graph_repository.get_designated_edge_ids([designated_edge_id, other_edge_id])

    assert result == {designated_edge_id}


async def test_get_designated_edge_ids_ignores_kinds_outside_car_stress_set(road_graph_repository, road_graph_session):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    # national_cycle_routeはCAR_STRESS_DESIGNATION_KINDSに含まれない（今回未実装のkind）。
    await _insert_designation_attribute(road_graph_session, 100, "national_cycle_route")
    await road_graph_session.commit()

    result = await road_graph_repository.get_designated_edge_ids([edge_id])

    assert result == set()


async def test_get_edge_materials_batch_returns_empty_for_empty_input(road_graph_repository):
    batch = await road_graph_repository.get_edge_materials_batch([])
    assert batch.surface_attributes == {}
    assert batch.edge_attribute_counts == {}
    assert batch.way_tags == {}
    assert batch.elevation_attributes == {}
    assert batch.designated_edge_ids == set()


async def test_get_edge_materials_batch_combines_all_five_materials_correctly(road_graph_repository, road_graph_session):
    # 改善計画T248: 5メソッド個別呼び出しと同じ意味（該当行なしの扱い含む）を、
    # 1回のJOINクエリへ統合した後も保つことを確認する回帰テスト。
    way = WaySpec(
        osm_way_id=100, node_ids=[1, 2], highway="residential", surface="asphalt",
        tags={"lanes": "2"},
    )
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_ids = list(graph.edges.keys())
    fwd_edge_id = next(e for e in edge_ids if e.endswith("-fwd"))
    bwd_edge_id = next(e for e in edge_ids if e.endswith("-bwd"))

    # edge_attribute_counts・elevation_attributesはfwd側のみに投入し、
    # 「該当行が無いEdge」の扱い（key自体を含めない）をbwd側で検証する。
    await road_graph_session.execute(
        insert(EdgeAttributeCountsRow).values(
            edge_id=fwd_edge_id, accident_count=1.5, stop_count=2, intersection_count=3,
            computed_at=datetime.now(timezone.utc),
        )
    )
    elevation = ElevationAttribute(
        edge_id=fwd_edge_id, start_elevation_m=10.0, end_elevation_m=15.0,
        elevation_gain_m=5.0, elevation_loss_m=0.0, average_grade=1.2, max_grade=1.2, min_grade=1.2,
        data_source="gsi", data_version="v1",
        calculated_at=datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
    )
    await road_graph_repository.save_elevation_attributes([elevation])
    # designationはosm_way_id単位のため、fwd・bwd両方が該当する。
    await _insert_designation_attribute(road_graph_session, 100, "emergency_transport")
    await road_graph_session.commit()

    batch = await road_graph_repository.get_edge_materials_batch(
        [fwd_edge_id, bwd_edge_id, "nonexistent-edge"]
    )

    # surface_attributes・way_tagsはLEFT JOINのため実在するEdgeは両方とも必ずkeyを持つ
    # （存在しないEdgeのみ除外される）。
    assert set(batch.surface_attributes.keys()) == {fwd_edge_id, bwd_edge_id}
    assert batch.surface_attributes[fwd_edge_id] == "asphalt"
    assert batch.surface_attributes[bwd_edge_id] == "asphalt"
    assert set(batch.way_tags.keys()) == {fwd_edge_id, bwd_edge_id}
    assert batch.way_tags[fwd_edge_id] == {"lanes": "2"}

    # edge_attribute_counts・elevation_attributesは該当行が無いbwdのkey自体が無い。
    assert set(batch.edge_attribute_counts.keys()) == {fwd_edge_id}
    counts = batch.edge_attribute_counts[fwd_edge_id]
    assert (counts.accident_count, counts.stop_count, counts.intersection_count) == (1.5, 2, 3)
    assert set(batch.elevation_attributes.keys()) == {fwd_edge_id}
    assert batch.elevation_attributes[fwd_edge_id].start_elevation_m == 10.0

    # designationはosm_way_id単位のためfwd・bwd両方。
    assert batch.designated_edge_ids == {fwd_edge_id, bwd_edge_id}


async def test_get_nearest_way_tags_is_designated_true_near_designated_edge(road_graph_repository, road_graph_session):
    """改善計画T76の回帰テスト: is_designatedは以前get_nearest_designated_flagsという
    専用メソッドだったが、同一サンプル点集合に対する3本目の独立KNNだったため
    get_nearest_way_tagsへ統合した。"""
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    await _insert_designation_attribute(road_graph_session, 100, "critical_logistics")
    await road_graph_session.commit()

    result = await road_graph_repository.get_nearest_way_tags([NODE1, NODE3], max_distance_m=30.0)

    assert [is_designated for _, _, is_designated in result] == [True, False]


async def _mark_tile_cached(session, zoom: int, x: int, y: int) -> None:
    """road_graph_tilesへ直接INSERT（UPSERT）する。改善計画: リポジトリの`mark_tile_cached`
    （実行時コードから未使用のため削除済み。書き込みは`app/batch/import_pbf.py`の
    `_mark_tiles`が唯一の実装）の代わりに、テストデータ準備用としてここに置く。"""
    await session.execute(
        text(
            "INSERT INTO road_graph_tiles (zoom, x, y, fetched_at) VALUES (:zoom, :x, :y, now()) "
            "ON CONFLICT (zoom, x, y) DO UPDATE SET fetched_at = EXCLUDED.fetched_at"
        ),
        {"zoom": zoom, "x": x, "y": y},
    )


async def test_get_cached_tiles_returns_empty_set_before_marking(road_graph_repository):
    assert await road_graph_repository.get_cached_tiles(zoom=12, tiles=[(1, 1)]) == set()


async def test_get_cached_tiles_returns_marked_tile_after_marking(road_graph_repository, road_graph_session):
    await _mark_tile_cached(road_graph_session, zoom=12, x=1, y=1)

    assert await road_graph_repository.get_cached_tiles(zoom=12, tiles=[(1, 1), (1, 2)]) == {(1, 1)}
    # 別ズームは影響を受けない
    assert await road_graph_repository.get_cached_tiles(zoom=13, tiles=[(1, 1)]) == set()


async def test_marking_tile_cached_twice_is_idempotent(road_graph_repository, road_graph_session):
    await _mark_tile_cached(road_graph_session, zoom=12, x=1, y=1)
    await _mark_tile_cached(road_graph_session, zoom=12, x=1, y=1)  # 再マークしても例外なし

    assert await road_graph_repository.get_cached_tiles(zoom=12, tiles=[(1, 1)]) == {(1, 1)}


async def test_get_cached_tiles_returns_empty_set_for_empty_input(road_graph_repository):
    # 改善計画T229: タイル数ぶん個別に問い合わせるループを1クエリへ集約するために追加。
    assert await road_graph_repository.get_cached_tiles(zoom=12, tiles=[]) == set()


async def test_get_cached_tiles_returns_only_marked_tiles_in_one_query(road_graph_repository, road_graph_session):
    await _mark_tile_cached(road_graph_session, zoom=12, x=100, y=200)
    await _mark_tile_cached(road_graph_session, zoom=12, x=101, y=200)
    # 別ズームの同じx,yは対象外。
    await _mark_tile_cached(road_graph_session, zoom=13, x=100, y=200)

    result = await road_graph_repository.get_cached_tiles(
        zoom=12, tiles=[(100, 200), (101, 200), (102, 200)]
    )

    assert result == {(100, 200), (101, 200)}


# --- get_road_surface_tile_mvt（ST_AsMVTによるDB側MVT生成・カバレッジ判定込み1クエリ）---

# NODE1/NODE2（35.700付近）を含むz14タイル。テストデータの座標から逆算せず、
# tile_bounds_lonlatの結果で包含を検証してから使う（下のフィクスチャ的アサーション参照）。
MVT_Z, MVT_X, MVT_Y = 14, 14549, 6450
# get_road_surface_tile_mvtへ渡すz12祖先タイル（RegionServiceがtile_ancestorで計算する値と同じ）
MVT_COVERAGE_TILE = (12, MVT_X >> 2, MVT_Y >> 2)


def _mvt_tile_bbox():
    from app.domain.region import tile_bounds_lonlat

    bbox = tile_bounds_lonlat(MVT_Z, MVT_X, MVT_Y)
    # テストデータ（NODE1/NODE2）が本当にこのタイルへ入っている前提の自己検証
    assert bbox.min_latitude <= NODE1[0] <= bbox.max_latitude
    assert bbox.min_longitude <= NODE1[1] <= bbox.max_longitude
    return bbox


async def _mark_mvt_coverage(road_graph_session):
    zoom, x, y = MVT_COVERAGE_TILE
    await _mark_tile_cached(road_graph_session, zoom=zoom, x=x, y=y)


async def test_get_road_surface_tile_mvt_returns_none_when_uncovered(road_graph_repository):
    """z12祖先タイルが未マーク（取込範囲外）ならNone（wayの有無に関わらずフォールバック判定へ）。"""
    way = WaySpec(osm_way_id=1, node_ids=[1, 2], highway="residential", surface="asphalt")
    await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )

    assert tile is None


async def test_get_road_surface_tile_mvt_returns_empty_bytes_when_covered_but_no_ways(road_graph_repository, road_graph_session):
    await _mark_mvt_coverage(road_graph_session)

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )

    assert tile == b""


async def test_get_road_surface_tile_mvt_encodes_layer_and_surface_classification(road_graph_repository, road_graph_session):
    """生成されたMVTがPythonエンコーダ（infrastructure/vector_tile.py）と同じ契約
    （レイヤー名road_surface・surface_good/surface/highwayプロパティ・不明はキー省略）を
    満たすことを、実際にデコードして確認する。分類はclassify_osm_surfaceと同じタグ集合
    （空白trim・小文字化込み）に従い、surfaceプロパティにも同じ正規化済みの生タグが入る。
    """
    import mapbox_vector_tile

    way_specs = [
        WaySpec(osm_way_id=1, node_ids=[1, 2], highway="residential", surface=" Asphalt "),  # trim+lower→良い
        WaySpec(osm_way_id=2, node_ids=[1, 2], highway="track", surface="gravel"),  # 悪い
        WaySpec(osm_way_id=3, node_ids=[1, 2], highway="residential"),  # タグ無し→不明
        WaySpec(osm_way_id=4, node_ids=[1, 2], highway="residential", surface="mystery_tag"),  # 未知→不明
    ]
    await road_graph_repository.save_raw_ways(way_specs, {1: NODE1, 2: NODE2})
    await _mark_mvt_coverage(road_graph_session)

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )

    decoded = mapbox_vector_tile.decode(tile)
    assert set(decoded.keys()) == {"road_surface"}
    properties = sorted(
        (feature["properties"] for feature in decoded["road_surface"]["features"]),
        key=lambda p: p.get("surface") or "",
    )
    # 不明（タグ無し・未知タグ）はsurface_goodキー自体が省略される（フロントエンドの
    # ["get","surface_good"]==null判定＝グレー表示、Pythonエンコーダと同じ挙動）。
    # surfaceタグ無しも同様にsurfaceキーごと省略される。bicycle_infraはhighwayさえ分かれば
    # 常に決まる（静的道路属性P0、いずれもtags未設定の4件はどちらもhighway=residential/track
    # で「roadway」になる）。車ストレスの材料タグ（maxspeed_kmh/lanes_count/motor_vehicle_no、
    # 改善計画: 交通ストレスレシピ外出し基盤）はcycleway等のタグ自体が
    # 無いためすべて省略される（最終値はもうSQL側では計算しない、ファイル冒頭コメント参照）。
    # smoothness/tunnel/bridgeもtags自体が空のためキーが省略される。
    assert properties == [
        {"osm_way_id": 3, "highway": "residential", "bicycle_infra": "roadway"},
        {
            "osm_way_id": 1,
            "surface_good": True,
            "surface": "asphalt",
            "highway": "residential",
            "bicycle_infra": "roadway",
        },
        {
            "osm_way_id": 2,
            "surface_good": False,
            "surface": "gravel",
            "highway": "track",
            "bicycle_infra": "roadway",
        },
        {
            "osm_way_id": 4,
            "surface": "mystery_tag",
            "highway": "residential",
            "bicycle_infra": "roadway",
        },
    ]


async def test_get_road_surface_tile_mvt_excludes_ways_outside_tile(road_graph_repository, road_graph_session):
    import mapbox_vector_tile

    way_specs = [
        WaySpec(osm_way_id=1, node_ids=[1, 2], highway="residential", surface="asphalt"),  # タイル内
        WaySpec(osm_way_id=2, node_ids=[3, 4], highway="residential", surface="asphalt"),  # タイル外(35.75付近)
    ]
    await road_graph_repository.save_raw_ways(way_specs, {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4})
    await _mark_mvt_coverage(road_graph_session)

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )

    decoded = mapbox_vector_tile.decode(tile)
    assert len(decoded["road_surface"]["features"]) == 1


async def test_get_road_surface_tile_mvt_encodes_smoothness_tunnel_bridge(road_graph_repository, road_graph_session):
    """静的道路属性P0: smoothnessは生タグの正規化のみ（surfaceと同じ流儀）、
    tunnel/bridgeは'yes'のときだけtrueが焼かれ、それ以外はキー省略。"""
    import mapbox_vector_tile

    way_specs = [
        WaySpec(
            osm_way_id=1, node_ids=[1, 2], highway="residential",
            tags={"smoothness": " Good ", "tunnel": "yes"},
        ),
        WaySpec(
            osm_way_id=2, node_ids=[1, 2], highway="residential", tags={"bridge": "yes"},
        ),
        WaySpec(osm_way_id=3, node_ids=[1, 2], highway="residential", tags={"tunnel": "no"}),
    ]
    await road_graph_repository.save_raw_ways(way_specs, {1: NODE1, 2: NODE2})
    await _mark_mvt_coverage(road_graph_session)

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )
    decoded = mapbox_vector_tile.decode(tile)
    properties = [f["properties"] for f in decoded["road_surface"]["features"]]

    tunnel_way = next(p for p in properties if p.get("smoothness") == "good")
    assert tunnel_way["tunnel"] is True
    assert "bridge" not in tunnel_way

    bridge_way = next(p for p in properties if p.get("bridge") is True)
    assert "tunnel" not in bridge_way
    assert "smoothness" not in bridge_way

    tunnel_no_way = next(p for p in properties if "smoothness" not in p and "bridge" not in p)
    assert "tunnel" not in tunnel_no_way  # tunnel=noはfalseではなくキー自体を省略する


async def test_get_road_surface_tile_mvt_encodes_oneway(road_graph_repository, road_graph_session):
    """改善計画T289: 一方通行はosm_raw_ways.direction（forward/backward/both）から
    算出する。both（双方向）はキー省略、forward/backwardはtrueが焼かれる。"""
    import mapbox_vector_tile

    way_specs = [
        WaySpec(osm_way_id=1, node_ids=[1, 2], highway="residential", direction="forward"),
        WaySpec(osm_way_id=2, node_ids=[1, 2], highway="residential", direction="backward"),
        WaySpec(osm_way_id=3, node_ids=[1, 2], highway="residential", direction="both"),
    ]
    await road_graph_repository.save_raw_ways(way_specs, {1: NODE1, 2: NODE2})
    await _mark_mvt_coverage(road_graph_session)

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )
    decoded = mapbox_vector_tile.decode(tile)
    properties_by_way_id = {p["osm_way_id"]: p for p in [f["properties"] for f in decoded["road_surface"]["features"]]}

    assert properties_by_way_id[1]["oneway"] is True
    assert properties_by_way_id[2]["oneway"] is True
    assert "oneway" not in properties_by_way_id[3]  # both（双方向）はキー自体を省略する


async def test_get_road_surface_tile_mvt_bicycle_infra_matches_domain_traffic(road_graph_repository, road_graph_session):
    """SQLのbicycle_infra CASE式がdomain/traffic.py（正準の判定ロジック）と同じ結果になることを、
    複数のタグ組合せで突き合わせる（改善計画: 判定ロジックの二重実装ドリフト検知）。

    車ストレスの最終値はもうSQL側で計算しない（改善計画: 交通ストレスレシピ外出し基盤、
    ファイル冒頭コメント参照）ため、この突き合わせ対象からは外れた。材料タグの検証は
    test_get_road_surface_tile_mvt_car_stress_ingredients参照。
    """
    import mapbox_vector_tile

    from app.domain.traffic import classify_bicycle_infrastructure

    # highwayはこのテスト内で識別キーに使う（MVTのfeature順序はSQLのORDER BY省略により
    # 保証されないため、各fixtureが一意なhighway値を持つよう構成する）。
    fixtures: list[tuple[str | None, dict[str, str]]] = [
        ("cycleway", {}),
        ("primary", {"cycleway": "track"}),
        ("primary_link", {"cycleway:left": "lane"}),
        ("secondary", {"cycleway": "share_busway"}),
        ("footway", {"bicycle": "designated"}),
        ("path", {}),
        ("residential", {"bicycle": "no"}),
    ]
    way_specs = [
        WaySpec(osm_way_id=i + 1, node_ids=[1, 2], highway=highway, tags=tags)
        for i, (highway, tags) in enumerate(fixtures)
    ]
    await road_graph_repository.save_raw_ways(way_specs, {1: NODE1, 2: NODE2})
    await _mark_mvt_coverage(road_graph_session)

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )
    decoded = mapbox_vector_tile.decode(tile)
    assert len(decoded["road_surface"]["features"]) == len(fixtures)

    # osm_way_idはプロパティに含まれないため、highway+タグの組合せで対応付ける
    # （このテストのfixtureはhighway単体でも一意に区別できるよう設計）
    properties_by_highway = {f["properties"].get("highway"): f["properties"] for f in decoded["road_surface"]["features"]}

    for highway, tags in fixtures:
        expected_infra = classify_bicycle_infrastructure(tags, highway)
        actual = properties_by_highway[highway]
        assert actual.get("bicycle_infra") == expected_infra, (highway, tags)


async def test_get_road_surface_tile_mvt_car_stress_ingredients(road_graph_repository, road_graph_session):
    """車ストレスの材料タグ（maxspeed_kmh/lanes_count/motor_vehicle_no、改善計画:
    交通ストレスレシピ外出し基盤）と、night軸の材料タグ（lit、domain/registry_defaults.py:
    inputs=["lit","tunnel"]。かつては安全度軸の材料でもあったが、安全度軸自体はT148で
    削除済み）が、SQLで正しく抽出・正規化されることを確認する。最終値の計算はもうSQL側の
    責務ではない（frontend/src/components/Map/axisLayers.ts、domain/axis_definitions.pyの
    AXIS_DEFINITIONSが担う）ため、ここでは「材料タグがタグから正しく取り出せているか」
    だけを検証する。cycleway由来のタグ（cycleway_class）は改善計画T337でこのタイル
    プロパティ自体を削除したため、ここでの検証対象からも外れた（cycleway由来の材料は
    現在bicycle_infraのみタイルへ焼き込まれており、test_get_road_surface_tile_mvt_
    bicycle_infra_matches_domain_trafficで別途検証済み）。
    """
    import mapbox_vector_tile

    # highwayはこのテスト内で識別キーに使う（MVTのfeature順序はSQLのORDER BY省略により
    # 保証されないため、各fixtureが一意なhighway値を持つよう構成する）。
    fixtures: list[tuple[str, dict[str, str], dict[str, object]]] = [
        ("cycleway", {}, {}),
        ("footway", {"bicycle": "designated"}, {}),
        ("secondary_link", {"motor_vehicle": "no"}, {"motor_vehicle_no": True}),
        ("tertiary", {"maxspeed": "60"}, {"maxspeed_kmh": 60}),
        ("trunk", {"maxspeed": "30", "lanes": "2"}, {"maxspeed_kmh": 30, "lanes_count": 2}),
        ("trunk_link", {"lanes": "5"}, {"lanes_count": 5}),
        ("unclassified", {"lanes": "1"}, {"lanes_count": 1}),
        # 改善計画: 交通ストレスレシピ外出し基盤のコードレビューで発覚。maxspeed/lanes="0"は
        # 数値正規表現には一致するが、Python側のparse_maxspeed/parse_lanesは0以下を無効値
        # （unknown）として弾く。SQL側も同じ扱いにしないと、フロントのMapLibre expression
        # （0を「材料タグあり」として補正を発火させてしまう）とPython採点側で最終値が食い違う。
        ("living_street", {"maxspeed": "0"}, {}),
        ("track", {"lanes": "0"}, {}),
        # 安全度の材料タグ（改善計画: 安全度レシピ）。tunnelは既存プロパティを再利用するため
        # ここでは新規追加したlitのみ確認する。
        ("service", {"lit": "yes"}, {"lit": True}),
        ("path", {"lit": "no"}, {}),
    ]
    way_specs = [
        WaySpec(osm_way_id=i + 1, node_ids=[1, 2], highway=highway, tags=tags)
        for i, (highway, tags, _expected) in enumerate(fixtures)
    ]
    await road_graph_repository.save_raw_ways(way_specs, {1: NODE1, 2: NODE2})
    await _mark_mvt_coverage(road_graph_session)

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )
    decoded = mapbox_vector_tile.decode(tile)
    assert len(decoded["road_surface"]["features"]) == len(fixtures)

    properties_by_highway = {f["properties"].get("highway"): f["properties"] for f in decoded["road_surface"]["features"]}

    for highway, tags, expected in fixtures:
        actual = properties_by_highway[highway]
        for key in ("maxspeed_kmh", "lanes_count", "motor_vehicle_no", "lit"):
            assert actual.get(key) == expected.get(key), (highway, tags, key)

    # 改善計画T337回帰テスト: cycleway_classプロパティが誤って復活していないこと
    # （どの評価軸・地図表示からも参照されない未使用材料だったため削除済み）。
    assert all("cycleway_class" not in p for p in properties_by_highway.values())


async def test_get_road_surface_tile_mvt_designation_matches_designation_kinds(
    road_graph_repository, road_graph_session,
):
    """指定路線コンフレーション機構（外部静的データソース T51）: designationプロパティが
    domain/designation.py: CAR_STRESS_DESIGNATION_KINDSの2kindと一致することを突き合わせる
    （SQL⇔Python二重実装のドリフト検知）。

    改善計画T75: `_ROAD_SURFACE_TILE_MVT_SQL`のdesignation CASE式は
    domain/designation.py: CAR_STRESS_DESIGNATION_KINDSの2値をリテラルで直接埋め込む
    （2kind固定の設計）。この2値がドリフトしていないかをここで突き合わせる:
    集合の値自体が変わったらこのテストの期待値ごと更新が必要になり、SQL側の見直し漏れに
    気づける（kind追加時はSQLの構造自体の見直しが要る）。

    改善計画T74: 2kindの両方に該当するwayは3値目"both"として出力される（重複kind欠落対策）。
    designationへの車ストレス+1補正は（改善計画: 車ストレスレシピ外出し基盤により）
    もうSQL側の責務ではないため、この突き合わせ対象からは外れた
    （domain/traffic.py: car_stress_breakdownのdesignation_adjustment参照）。
    """
    import mapbox_vector_tile

    from app.domain.designation import CAR_STRESS_DESIGNATION_KINDS

    assert CAR_STRESS_DESIGNATION_KINDS == frozenset({"emergency_transport", "critical_logistics"})

    ert_way = WaySpec(osm_way_id=200, node_ids=[1, 2], highway="residential")
    cl_way = WaySpec(osm_way_id=202, node_ids=[1, 2], highway="secondary")
    plain_way = WaySpec(osm_way_id=201, node_ids=[1, 2], highway="tertiary")
    # 改善計画T74: N10・N12両方に該当するway（重複kind）は3値目"both"として出力される
    # （凡例で「緊急輸送道路」を非表示にしてもbothカテゴリとして表示され続ける）。
    both_way = WaySpec(osm_way_id=203, node_ids=[1, 2], highway="unclassified")
    ways = [ert_way, cl_way, plain_way, both_way]
    await road_graph_repository.save_raw_ways(ways, {1: NODE1, 2: NODE2})
    graph = build_road_graph(ways, {1: NODE1, 2: NODE2}, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    await _insert_designation_attribute(road_graph_session, 200, "emergency_transport")
    await _insert_designation_attribute(road_graph_session, 202, "critical_logistics")
    await _insert_designation_attribute(road_graph_session, 203, "emergency_transport")
    await _insert_designation_attribute(road_graph_session, 203, "critical_logistics")
    await road_graph_session.commit()
    await _mark_mvt_coverage(road_graph_session)

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )
    decoded = mapbox_vector_tile.decode(tile)
    properties_by_highway = {f["properties"].get("highway"): f["properties"] for f in decoded["road_surface"]["features"]}

    ert = properties_by_highway["residential"]
    assert ert.get("designation") == "emergency_transport"

    cl = properties_by_highway["secondary"]
    assert cl.get("designation") == "critical_logistics"

    plain = properties_by_highway["tertiary"]
    assert "designation" not in plain

    both = properties_by_highway["unclassified"]
    assert both.get("designation") == "both"


# --- get_distinct_material_values（改善計画T340: 軸スタジオの値入力UX改善） ---


async def test_get_distinct_material_values_returns_sorted_deduped_values(
    road_graph_repository, road_graph_session,
):
    """highway/surface/smoothnessの実データ値一覧が、重複無し・ソート済みで返る。
    surface/smoothnessは_ROAD_SURFACE_TILE_MVT_SQLと同じ正規化（lower/btrim）を適用する。
    """
    ways = [
        WaySpec(osm_way_id=300, node_ids=[1, 2], highway="residential", surface=" Asphalt "),
        WaySpec(osm_way_id=301, node_ids=[1, 2], highway="primary", surface="asphalt"),  # 正規化後重複
        WaySpec(osm_way_id=302, node_ids=[1, 2], highway="residential", tags={"smoothness": " Good "}),
        WaySpec(osm_way_id=303, node_ids=[1, 2], highway="track"),  # surface/smoothnessタグ無し
    ]
    await road_graph_repository.save_raw_ways(ways, {1: NODE1, 2: NODE2})
    await road_graph_session.commit()

    highway_values = await road_graph_repository.get_distinct_material_values("highway")
    surface_values = await road_graph_repository.get_distinct_material_values("surface")
    smoothness_values = await road_graph_repository.get_distinct_material_values("smoothness")

    assert highway_values == sorted({"residential", "primary", "track"})
    assert surface_values == ["asphalt"]  # 正規化後は1件に重複排除される
    assert smoothness_values == ["good"]


async def test_get_distinct_material_values_unsupported_material_returns_empty_list(road_graph_repository):
    # bicycle_infra等、事前に閉じた値集合を持つ材料（_MATERIAL_VALUE_COLUMN_EXPR未登録）は
    # DBへ問い合わせず空リストを返す。
    assert await road_graph_repository.get_distinct_material_values("bicycle_infra") == []
    assert await road_graph_repository.get_distinct_material_values("not_a_real_material") == []


# --- get_poi_tile_mvt（改善計画T54: 停止要因POI・交差点密度の可視化） ---

NODE5 = (35.6995, 139.6995)
NODE6 = (35.7005, 139.7005)


async def test_get_poi_tile_mvt_returns_none_when_uncovered(road_graph_repository):
    tile = await road_graph_repository.get_poi_tile_mvt(MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE)

    assert tile is None


async def test_get_poi_tile_mvt_returns_empty_bytes_when_covered_but_no_data(road_graph_repository, road_graph_session):
    await _mark_mvt_coverage(road_graph_session)

    tile = await road_graph_repository.get_poi_tile_mvt(MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE)

    assert tile == b""


async def test_get_poi_tile_mvt_encodes_stop_poi_kind(road_graph_repository, road_graph_session):
    """osm_raw_poisのkindがそのままstop_poiレイヤーのkindプロパティへ焼き込まれる。"""
    import mapbox_vector_tile

    await road_graph_session.execute(
        insert(OsmRawPoiRow),
        [
            {
                "osm_node_id": 1,
                "kind": "traffic_signals",
                "tags": {},
                "geom": from_shape(Point(NODE1[1], NODE1[0]), srid=4326),
                "updated_at": datetime.now(timezone.utc),
            },
            {
                "osm_node_id": 2,
                "kind": "level_crossing",
                "tags": {},
                "geom": from_shape(Point(NODE2[1], NODE2[0]), srid=4326),
                "updated_at": datetime.now(timezone.utc),
            },
        ],
    )
    await _mark_mvt_coverage(road_graph_session)

    tile = await road_graph_repository.get_poi_tile_mvt(MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE)

    decoded = mapbox_vector_tile.decode(tile)
    kinds = sorted(f["properties"]["kind"] for f in decoded["stop_poi"]["features"])
    assert kinds == ["level_crossing", "traffic_signals"]


# --- way_attribute_counts / raw_intersection_nodes（改善計画T145b「事実はタイルに、解釈は
# クライアントに」）。地図タイルへ焼き込むway単位の事実カウントの事前集計。 ---


async def test_rebuild_raw_intersection_nodes_detects_degree3_from_raw_ways(
    road_graph_repository, road_graph_session
):
    """osm_raw_ways.node_idsの隣接関係から次数3以上の生ノードだけが抽出される
    （Road Graph＝road_edges非依存。形状点・行き止まりは次数2以下で除外）。"""
    way_a = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    way_b = WaySpec(osm_way_id=101, node_ids=[2, 3], highway="residential")
    way_c = WaySpec(osm_way_id=102, node_ids=[2, 4], highway="residential")
    nodes = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4}
    await road_graph_repository.save_raw_ways([way_a, way_b, way_c], nodes)

    await road_graph_repository.rebuild_raw_intersection_nodes()
    await road_graph_session.commit()

    rows = (
        await road_graph_session.execute(
            text("SELECT osm_node_id, degree FROM raw_intersection_nodes ORDER BY osm_node_id")
        )
    ).all()
    assert rows == [(2, 3)]


async def test_recompute_way_attribute_counts_computes_per_way_facts(
    road_graph_repository, road_graph_session
):
    """way単位のカウント（意味論はedge単位版と同一: 事故=半径30m・involves_bicycleのみ・
    死亡重み、停止POI=半径15m・STOP_POI_KINDSのみ、交差点=半径30m・次数3以上の生ノード）と
    way長が計算・UPSERTされることを確認する。"""
    way_a = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    way_b = WaySpec(osm_way_id=101, node_ids=[2, 3], highway="residential")
    way_c = WaySpec(osm_way_id=102, node_ids=[2, 4], highway="residential")
    nodes = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4}
    await road_graph_repository.save_raw_ways([way_a, way_b, way_c], nodes)
    await road_graph_repository.rebuild_raw_intersection_nodes()

    # way_a近傍: 停止POI1件（signal）＋補給POI1件（除外されるべき）＋自転車事故1件
    await _insert_poi(road_graph_session, 900, "traffic_signals", *NODE1)
    await _insert_poi(road_graph_session, 901, "convenience", *NODE1)
    await _insert_accident(road_graph_session, "acc-1", 2024, *NODE1, involves_bicycle=True)
    # 自転車が関与しない事故は数えない（bicycle_only=true相当で固定）
    await _insert_accident(road_graph_session, "acc-2", 2024, *NODE1, involves_bicycle=False)
    await road_graph_session.commit()

    await road_graph_repository.recompute_way_attribute_counts(
        [100, 101, 102], datetime.now(timezone.utc)
    )
    await road_graph_session.commit()

    rows = {
        row[0]: row
        for row in (
            await road_graph_session.execute(
                text(
                    "SELECT osm_way_id, length_m, accident_count, stop_count, intersection_count "
                    "FROM way_attribute_counts ORDER BY osm_way_id"
                )
            )
        ).all()
    }
    assert set(rows.keys()) == {100, 101, 102}
    _, length_m, accident_count, stop_count, intersection_count = rows[100]
    assert length_m > 0
    assert accident_count == 1.0  # 自転車事故のみ・非死亡は重み1
    assert stop_count == 1  # convenienceは除外
    assert intersection_count == 1  # NODE2（次数3）が端点＝半径30m以内
    # way_b/way_cも共有端点NODE2の交差点を1件ずつ数える
    assert rows[101][4] == 1
    assert rows[102][4] == 1


async def test_get_road_surface_tile_mvt_encodes_per_km_densities(road_graph_repository, road_graph_session):
    """way_attribute_countsのカウントがkm正規化されてaccident_per_km/stop_per_km/
    intersection_per_kmプロパティとしてMVTへ焼き込まれる（0はキー省略）。"""
    import mapbox_vector_tile

    way_a = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    way_b = WaySpec(osm_way_id=101, node_ids=[2, 3], highway="residential")
    way_c = WaySpec(osm_way_id=102, node_ids=[2, 4], highway="residential")
    nodes = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4}
    await road_graph_repository.save_raw_ways([way_a, way_b, way_c], nodes)
    await road_graph_repository.rebuild_raw_intersection_nodes()
    await _insert_poi(road_graph_session, 900, "traffic_signals", *NODE1)
    await road_graph_session.commit()
    await road_graph_repository.recompute_way_attribute_counts(
        [100, 101, 102], datetime.now(timezone.utc)
    )
    await _mark_mvt_coverage(road_graph_session)

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )

    decoded = mapbox_vector_tile.decode(tile)
    features = {f["properties"]["osm_way_id"]: f["properties"] for f in decoded["road_surface"]["features"]}
    # way_a（NODE1-NODE2、約147m）: signal 1件 → stop_per_km ≈ 1000/長さm ≈ 6.8
    way_a_props = features[100]
    assert way_a_props["stop_per_km"] == pytest.approx(1000.0 / 147.0, rel=0.2)
    assert way_a_props["intersection_per_km"] > 0
    # 事故0件のwayはaccident_per_kmキー自体が省略される（NULLIFによるタイル軽量化）
    assert "accident_per_km" not in way_a_props
