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
from app.infrastructure.road_graph_models import OsmRawPoiRow

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


# --- 静的道路属性P1残り（交通ストレス・自転車インフラ・交差点密度の評価組み込み） ---


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
    """改善計画T90: 区間クリック時の交通ストレス内訳表示。get_nearest_way_tagsの空間マッチ
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
    isolated_edge_ids = [
        edge_id for edge_id, edge in graph.edges.items() if edge.osm_way_id == 200
    ]

    result = await road_graph_repository.get_intersection_counts(isolated_edge_ids, max_distance_m=30.0)

    assert all(count == 0 for count in result.values())


async def test_get_nearest_intersection_counts_returns_empty_list_for_empty_input(road_graph_repository):
    assert await road_graph_repository.get_nearest_intersection_counts([]) == []


async def test_get_nearest_intersection_counts_counts_intersections_near_each_point(road_graph_repository):
    way_a = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    way_b = WaySpec(osm_way_id=101, node_ids=[2, 3], highway="residential")
    way_c = WaySpec(osm_way_id=102, node_ids=[2, 4], highway="residential")
    nodes = {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4}
    graph = build_road_graph([way_a, way_b, way_c], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)

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


async def test_get_designated_edge_ids_ignores_kinds_outside_traffic_stress_set(road_graph_repository, road_graph_session):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_id = next(iter(graph.edges))

    # national_cycle_routeはTRAFFIC_STRESS_DESIGNATION_KINDSに含まれない（今回未実装のkind）。
    await _insert_designation_attribute(road_graph_session, 100, "national_cycle_route")
    await road_graph_session.commit()

    result = await road_graph_repository.get_designated_edge_ids([edge_id])

    assert result == set()


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


async def test_is_tile_cached_returns_false_before_marking(road_graph_repository):
    assert await road_graph_repository.is_tile_cached(zoom=12, x=1, y=1) is False


async def test_mark_tile_cached_then_is_tile_cached_returns_true(road_graph_repository):
    await road_graph_repository.mark_tile_cached(zoom=12, x=1, y=1)

    assert await road_graph_repository.is_tile_cached(zoom=12, x=1, y=1) is True
    # 隣接タイル・別ズームは影響を受けない
    assert await road_graph_repository.is_tile_cached(zoom=12, x=1, y=2) is False
    assert await road_graph_repository.is_tile_cached(zoom=13, x=1, y=1) is False


async def test_mark_tile_cached_is_idempotent(road_graph_repository):
    await road_graph_repository.mark_tile_cached(zoom=12, x=1, y=1)
    await road_graph_repository.mark_tile_cached(zoom=12, x=1, y=1)  # 再マークしても例外なし

    assert await road_graph_repository.is_tile_cached(zoom=12, x=1, y=1) is True


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


async def _mark_mvt_coverage(road_graph_repository):
    zoom, x, y = MVT_COVERAGE_TILE
    await road_graph_repository.mark_tile_cached(zoom=zoom, x=x, y=y)


async def test_get_road_surface_tile_mvt_returns_none_when_uncovered(road_graph_repository):
    """z12祖先タイルが未マーク（取込範囲外）ならNone（wayの有無に関わらずフォールバック判定へ）。"""
    way = WaySpec(osm_way_id=1, node_ids=[1, 2], highway="residential", surface="asphalt")
    await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )

    assert tile is None


async def test_get_road_surface_tile_mvt_returns_empty_bytes_when_covered_but_no_ways(road_graph_repository):
    await _mark_mvt_coverage(road_graph_repository)

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )

    assert tile == b""


async def test_get_road_surface_tile_mvt_encodes_layer_and_surface_classification(road_graph_repository):
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
    await _mark_mvt_coverage(road_graph_repository)

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
    # で「roadway」になる）。交通ストレスの材料タグ（cycleway_class/maxspeed_kmh/lanes_count/
    # motor_vehicle_no、改善計画: 交通ストレスレシピ外出し基盤）はcycleway等のタグ自体が
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


async def test_get_road_surface_tile_mvt_excludes_ways_outside_tile(road_graph_repository):
    import mapbox_vector_tile

    way_specs = [
        WaySpec(osm_way_id=1, node_ids=[1, 2], highway="residential", surface="asphalt"),  # タイル内
        WaySpec(osm_way_id=2, node_ids=[3, 4], highway="residential", surface="asphalt"),  # タイル外(35.75付近)
    ]
    await road_graph_repository.save_raw_ways(way_specs, {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4})
    await _mark_mvt_coverage(road_graph_repository)

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )

    decoded = mapbox_vector_tile.decode(tile)
    assert len(decoded["road_surface"]["features"]) == 1


async def test_get_road_surface_tile_mvt_encodes_smoothness_tunnel_bridge(road_graph_repository):
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
    await _mark_mvt_coverage(road_graph_repository)

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


async def test_get_road_surface_tile_mvt_bicycle_infra_matches_domain_traffic(road_graph_repository):
    """SQLのbicycle_infra CASE式がdomain/traffic.py（正準の判定ロジック）と同じ結果になることを、
    複数のタグ組合せで突き合わせる（改善計画: 判定ロジックの二重実装ドリフト検知）。

    交通ストレスの最終値はもうSQL側で計算しない（改善計画: 交通ストレスレシピ外出し基盤、
    ファイル冒頭コメント参照）ため、この突き合わせ対象からは外れた。材料タグの検証は
    test_get_road_surface_tile_mvt_traffic_stress_ingredients参照。
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
    await _mark_mvt_coverage(road_graph_repository)

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


async def test_get_road_surface_tile_mvt_traffic_stress_ingredients(road_graph_repository):
    """交通ストレス・安全度の材料タグ（cycleway_class/maxspeed_kmh/lanes_count/
    motor_vehicle_no・shoulder/lit、改善計画: 交通ストレスレシピ外出し基盤/安全度レシピ）が
    SQLで正しく抽出・正規化されることを確認する。最終値の計算はもうSQL側の責務ではない
    （frontend/src/components/Map/trafficStressExpression.ts・safetyExpression.ts、
    domain/traffic.py: traffic_stress_breakdown・domain/safety.py: safety_breakdownが担う）
    ため、ここでは「材料タグがタグから正しく取り出せているか」だけを検証する。
    """
    import mapbox_vector_tile

    # highwayはこのテスト内で識別キーに使う（MVTのfeature順序はSQLのORDER BY省略により
    # 保証されないため、各fixtureが一意なhighway値を持つよう構成する）。
    fixtures: list[tuple[str, dict[str, str], dict[str, object]]] = [
        ("cycleway", {}, {}),
        ("primary", {"cycleway": "track"}, {"cycleway_class": "track"}),
        ("primary_link", {"cycleway:left": "lane"}, {"cycleway_class": "lane"}),
        ("secondary", {"cycleway": "share_busway"}, {"cycleway_class": "shared"}),
        ("tertiary_link", {"cycleway": "shared_lane"}, {"cycleway_class": "shared"}),
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
        # ここでは新規追加したshoulder/litのみ確認する。
        ("residential", {"shoulder": "yes"}, {"shoulder": True}),
        ("service", {"lit": "yes"}, {"lit": True}),
        ("path", {"shoulder": "no"}, {}),
    ]
    way_specs = [
        WaySpec(osm_way_id=i + 1, node_ids=[1, 2], highway=highway, tags=tags)
        for i, (highway, tags, _expected) in enumerate(fixtures)
    ]
    await road_graph_repository.save_raw_ways(way_specs, {1: NODE1, 2: NODE2})
    await _mark_mvt_coverage(road_graph_repository)

    tile = await road_graph_repository.get_road_surface_tile_mvt(
        MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE
    )
    decoded = mapbox_vector_tile.decode(tile)
    assert len(decoded["road_surface"]["features"]) == len(fixtures)

    properties_by_highway = {f["properties"].get("highway"): f["properties"] for f in decoded["road_surface"]["features"]}

    for highway, tags, expected in fixtures:
        actual = properties_by_highway[highway]
        for key in ("cycleway_class", "maxspeed_kmh", "lanes_count", "motor_vehicle_no", "shoulder", "lit"):
            assert actual.get(key) == expected.get(key), (highway, tags, key)


async def test_get_road_surface_tile_mvt_designation_matches_designation_kinds(
    road_graph_repository, road_graph_session,
):
    """指定路線コンフレーション機構（外部静的データソース T51）: designationプロパティが
    domain/designation.py: TRAFFIC_STRESS_DESIGNATION_KINDSの2kindと一致することを突き合わせる
    （SQL⇔Python二重実装のドリフト検知）。

    改善計画T75: `_ROAD_SURFACE_TILE_MVT_SQL`のdesignation CASE式は
    domain/designation.py: TRAFFIC_STRESS_DESIGNATION_KINDSの2値をリテラルで直接埋め込む
    （2kind固定の設計）。この2値がドリフトしていないかをここで突き合わせる:
    集合の値自体が変わったらこのテストの期待値ごと更新が必要になり、SQL側の見直し漏れに
    気づける（kind追加時はSQLの構造自体の見直しが要る）。

    改善計画T74: 2kindの両方に該当するwayは3値目"both"として出力される（重複kind欠落対策）。
    designationへの交通ストレス+1補正は（改善計画: 交通ストレスレシピ外出し基盤により）
    もうSQL側の責務ではないため、この突き合わせ対象からは外れた
    （domain/traffic.py: traffic_stress_breakdownのdesignation_adjustment参照）。
    """
    import mapbox_vector_tile

    from app.domain.designation import TRAFFIC_STRESS_DESIGNATION_KINDS

    assert TRAFFIC_STRESS_DESIGNATION_KINDS == frozenset({"emergency_transport", "critical_logistics"})

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
    await _mark_mvt_coverage(road_graph_repository)

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


# --- get_poi_tile_mvt（改善計画T54: 停止要因POI・交差点密度の可視化） ---

NODE5 = (35.6995, 139.6995)
NODE6 = (35.7005, 139.7005)


async def test_get_poi_tile_mvt_returns_none_when_uncovered(road_graph_repository):
    tile = await road_graph_repository.get_poi_tile_mvt(MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE)

    assert tile is None


async def test_get_poi_tile_mvt_returns_empty_bytes_when_covered_but_no_data(road_graph_repository):
    await _mark_mvt_coverage(road_graph_repository)

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
    await _mark_mvt_coverage(road_graph_repository)

    tile = await road_graph_repository.get_poi_tile_mvt(MVT_Z, MVT_X, MVT_Y, _mvt_tile_bbox(), MVT_COVERAGE_TILE)

    decoded = mapbox_vector_tile.decode(tile)
    kinds = sorted(f["properties"]["kind"] for f in decoded["stop_poi"]["features"])
    assert kinds == ["level_crossing", "traffic_signals"]
