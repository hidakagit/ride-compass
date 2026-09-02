import pickle

from app.domain.attributes import (
    EdgeAttributeCounts,
    EdgeMaterialBundle,
    EdgeMaterialTable,
    ElevationAttribute,
    compute_elevation_attribute,
    surface_by_edge_id,
)
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.route import Coordinates

P1 = Coordinates(latitude=35.700, longitude=139.700)
P2 = Coordinates(latitude=35.701, longitude=139.700)
P3 = Coordinates(latitude=35.702, longitude=139.700)
P4 = Coordinates(latitude=35.703, longitude=139.700)


def test_compute_elevation_attribute_uphill():
    attr = compute_elevation_attribute("edge-1", [P1, P2, P3], [10.0, 20.0, 40.0], data_source="test")

    assert attr.edge_id == "edge-1"
    assert attr.start_elevation_m == 10.0
    assert attr.end_elevation_m == 40.0
    assert attr.elevation_gain_m == 30.0
    assert attr.elevation_loss_m == 0.0
    assert attr.max_grade is not None and attr.max_grade > 0
    assert attr.min_grade is not None and attr.min_grade > 0
    assert attr.average_grade is not None and attr.average_grade > 0
    assert attr.data_source == "test"
    assert attr.calculated_at


def test_compute_elevation_attribute_downhill_has_loss_and_negative_grade():
    attr = compute_elevation_attribute("edge-1", [P1, P2, P3], [40.0, 20.0, 10.0], data_source="test")

    assert attr.elevation_gain_m == 0.0
    assert attr.elevation_loss_m == 30.0
    assert attr.max_grade is not None and attr.max_grade < 0
    assert attr.min_grade is not None and attr.min_grade < 0
    assert attr.average_grade is not None and attr.average_grade < 0


def test_compute_elevation_attribute_mixed_gain_and_loss():
    attr = compute_elevation_attribute("edge-1", [P1, P2, P3], [10.0, 30.0, 15.0], data_source="test")

    assert attr.elevation_gain_m == 20.0
    assert attr.elevation_loss_m == 15.0
    assert attr.max_grade is not None and attr.max_grade > 0  # 登り区間
    assert attr.min_grade is not None and attr.min_grade < 0  # 下り区間


def test_compute_elevation_attribute_ignores_none_values():
    attr = compute_elevation_attribute("edge-1", [P1, P2, P3], [10.0, None, 20.0], data_source="test")

    # 改善計画T463: P1(10.0)→P3(20.0)は元の点列で隣接していない（間のP2が欠損）ため、
    # start/end_elevationはvalid点から算出するが、gain/loss/gradeへは寄与しない
    # （欠損区間の実際の起伏を「一律10m上昇」と均してしまうバグの回帰テスト）。
    assert attr.start_elevation_m == 10.0
    assert attr.end_elevation_m == 20.0
    assert attr.elevation_gain_m == 0.0
    assert attr.elevation_loss_m == 0.0
    assert attr.max_grade is None
    assert attr.min_grade is None
    # average_gradeは開始・終了標高とtotal_distance_mから算出するため、欠損の有無に
    # 関わらず引き続き算出される（gain/loss/gradeとは独立した扱い）。
    assert attr.average_grade is not None and attr.average_grade > 0


def test_compute_elevation_attribute_only_counts_truly_adjacent_pairs_for_gain():
    # P1(10)→P2(20)は元の点列で隣接（gain 10に寄与）。P2(20)→P4(30)は間のP3が欠損して
    # おり隣接していないためgainに寄与しない。合計gainは20ではなく10になるはず
    # （改善計画T463の回帰テスト）。
    attr = compute_elevation_attribute("edge-1", [P1, P2, P3, P4], [10.0, 20.0, None, 30.0], data_source="test")

    assert attr.start_elevation_m == 10.0
    assert attr.end_elevation_m == 30.0
    assert attr.elevation_gain_m == 10.0
    assert attr.elevation_loss_m == 0.0
    # max/min_gradeはP1→P2ペアのみから算出される（P2→P4は欠損を挟むため寄与しない）。
    assert attr.max_grade is not None and attr.max_grade > 0
    assert attr.min_grade is not None and attr.min_grade > 0


def test_compute_elevation_attribute_returns_all_none_when_fewer_than_two_valid_points():
    attr = compute_elevation_attribute("edge-1", [P1, P2], [10.0, None], data_source="test")

    assert attr.edge_id == "edge-1"
    assert attr.start_elevation_m is None
    assert attr.elevation_gain_m is None
    assert attr.average_grade is None
    assert attr.data_source == "test"
    assert attr.calculated_at


def _make_graph(edges: dict[str, DirectedEdge]) -> RoadGraph:
    node = Node(node_id="node-1", latitude=35.7, longitude=139.7)
    return RoadGraph(graph_version="v1", nodes={"node-1": node}, edges=edges)


def test_surface_by_edge_id_maps_by_osm_way_id():
    edge = DirectedEdge(
        edge_id="edge-1",
        from_node_id="node-1",
        to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]],
        distance_m=100.0,
        osm_way_id=100,
    )
    graph = _make_graph({"edge-1": edge})

    surfaces = surface_by_edge_id(graph, surface_by_way_id={100: "asphalt"})

    assert surfaces["edge-1"] == "asphalt"


def test_surface_by_edge_id_unknown_way_id_is_none():
    edge = DirectedEdge(
        edge_id="edge-1",
        from_node_id="node-1",
        to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]],
        distance_m=100.0,
        osm_way_id=999,
    )
    graph = _make_graph({"edge-1": edge})

    surfaces = surface_by_edge_id(graph, surface_by_way_id={100: "asphalt"})

    assert surfaces["edge-1"] is None


def test_surface_by_edge_id_edge_without_osm_way_id_is_none():
    edge = DirectedEdge(
        edge_id="edge-1",
        from_node_id="node-1",
        to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]],
        distance_m=100.0,
        osm_way_id=None,
    )
    graph = _make_graph({"edge-1": edge})

    surfaces = surface_by_edge_id(graph, surface_by_way_id={100: "asphalt"})

    assert surfaces["edge-1"] is None


# --- EdgeMaterialTable（改善計画T546、T538再検討案C1）---


def _full_bundle(edge_id: str) -> EdgeMaterialBundle:
    """全フィールドが埋まったbundle（標高・件数どちらも行あり）。"""
    return EdgeMaterialBundle(
        surface="asphalt",
        way_tags={"highway": "residential", "surface": "asphalt"},
        attribute_counts=EdgeAttributeCounts(accident_count=1.5, stop_count=2, intersection_count=3),
        elevation_attribute=ElevationAttribute(
            edge_id=edge_id,
            start_elevation_m=10.1,
            end_elevation_m=25.3,
            elevation_gain_m=15.2,
            elevation_loss_m=0.0,
            average_grade=3.5,
            max_grade=5.5,
            min_grade=1.2,
            data_source="gsi-dem",
            data_version="v2",
            calculated_at="2026-09-02T00:00:00+00:00",
        ),
        is_designated=True,
    )


def _bundle_with_partial_elevation(edge_id: str) -> EdgeMaterialBundle:
    """標高の行自体は存在するが、有効な標高点が2点未満で全フィールドNoneのケース
    （`compute_elevation_attribute`の「行はあるがフィールドはNone」パターン、
    `elevation_attribute is None`とは区別する必要がある境界値）。"""
    return EdgeMaterialBundle(
        surface=None,
        way_tags={},
        attribute_counts=None,
        elevation_attribute=ElevationAttribute(
            edge_id=edge_id, data_source="gsi-dem", calculated_at="2026-09-02T00:00:00+00:00",
        ),
        is_designated=False,
    )


def _bare_bundle() -> EdgeMaterialBundle:
    """行が一切無いbundle（標高未計算・件数未集計・タグ未取得・非指定路線）。"""
    return EdgeMaterialBundle(
        surface=None, way_tags={}, attribute_counts=None, elevation_attribute=None, is_designated=False,
    )


def test_edge_material_table_from_bundles_empty_edge_ids_roundtrips():
    # 境界ケース: 空タイル（Edge0件）。T536で本番発覚した空タイル混在ケースの土台。
    table = EdgeMaterialTable.from_bundles([], {})

    assert len(table) == 0
    assert table.get("missing") is None
    assert list(table.values()) == []
    legacy = table.to_legacy_dicts()
    assert legacy.elevation_attributes == {}
    assert legacy.surface_attributes == {}
    assert legacy.designated_edge_ids == set()


def test_edge_material_table_get_returns_none_when_bundle_absent_for_edge_id():
    # `EdgeMaterialBundle.way_tags`自体の`{}`（bundle_with_partial_elevationやbare_bundle
    # ）とは独立して、「bundleそのものが無いedge_id」はget()がNoneを返す
    # （元の`materials.get(edge_id)`と同じ意味論、docs/tasks/T546.md「実装リスク」参照）。
    table = EdgeMaterialTable.from_bundles(["e1", "e2"], {"e1": _full_bundle("e1")})

    assert table.get("e1") == _full_bundle("e1")
    assert table.get("e2") is None
    assert len(table) == 1


def test_edge_material_table_distinguishes_no_bundle_from_bundle_with_empty_way_tags():
    # way_tags={}（タグ取得済みだが空）と、bundle自体が無い（get()がNone）を混同しない。
    table = EdgeMaterialTable.from_bundles(["e1"], {"e1": _bare_bundle()})

    bundle = table.get("e1")
    assert bundle is not None
    assert bundle.way_tags == {}


def test_edge_material_table_distinguishes_missing_elevation_row_from_row_with_none_fields():
    # elevation_attribute自体が無い（行が無い）ケースと、行はあるが有効点不足で全フィールド
    # Noneのケース（_bundle_with_partial_elevation）を区別する（実装リスク節の要求）。
    table = EdgeMaterialTable.from_bundles(
        ["e1", "e2"],
        {"e1": _bundle_with_partial_elevation("e1"), "e2": _bare_bundle()},
    )

    e1 = table.get("e1")
    assert e1.elevation_attribute is not None
    assert e1.elevation_attribute.start_elevation_m is None
    assert e1.elevation_attribute.data_source == "gsi-dem"

    e2 = table.get("e2")
    assert e2.elevation_attribute is None


def test_edge_material_table_roundtrip_at_realistic_scale():
    """実データ規模相当（数万Edge）のfixtureで、全Edgeについて
    `table.get(edge_id) == 元のbundle`が成り立つことを確認する往復テスト（実装リスク節が
    要求する優先度。単純な数件のfixtureでは列指向変換の境界バグ[要素の対応ズレ・型変換の
    丸め誤差等]を検出できないため、実データ規模で行う）。"""
    n = 30_000
    edge_ids = [f"way-{i}-seg0-fwd" for i in range(n)]
    bundles: dict[str, EdgeMaterialBundle] = {}
    for i, edge_id in enumerate(edge_ids):
        remainder = i % 4
        if remainder == 0:
            bundles[edge_id] = _full_bundle(edge_id)
        elif remainder == 1:
            bundles[edge_id] = _bundle_with_partial_elevation(edge_id)
        elif remainder == 2:
            bundles[edge_id] = _bare_bundle()
        else:
            # 一部フィールドだけ欠損した組み合わせ（件数はあるが標高は無い等）。
            bundles[edge_id] = EdgeMaterialBundle(
                surface="gravel" if i % 8 == 3 else None,
                way_tags={"bicycle": "no"} if i % 16 == 3 else {},
                attribute_counts=EdgeAttributeCounts(
                    accident_count=float(i % 5), stop_count=i % 3, intersection_count=i % 2
                ),
                elevation_attribute=None,
                is_designated=(i % 32 == 3),
            )

    table = EdgeMaterialTable.from_bundles(edge_ids, bundles)

    assert len(table) == n
    for edge_id in edge_ids:
        assert table.get(edge_id) == bundles[edge_id]

    # pickle往復（tile_persistent_cache.pyが実際に使う経路）でも同じ結果になることを確認する。
    restored = pickle.loads(pickle.dumps(table, protocol=pickle.HIGHEST_PROTOCOL))
    for edge_id in edge_ids:
        assert restored.get(edge_id) == bundles[edge_id]


def test_edge_material_table_to_legacy_dicts_matches_manual_dict_construction():
    """`to_legacy_dicts()`が、旧`build_static_edge_score_matrix`が`materials.items()`から
    直接構築していたのと同じ内容の辞書群を返すことを確認する（改善計画T546、対応方針
    項目1）。"""
    bundles = {
        "e1": _full_bundle("e1"),
        "e2": _bundle_with_partial_elevation("e2"),
        "e3": _bare_bundle(),
    }
    edge_ids = list(bundles.keys())
    table = EdgeMaterialTable.from_bundles(edge_ids, bundles)

    legacy = table.to_legacy_dicts()

    expected_elevation_attributes = {
        edge_id: bundle.elevation_attribute for edge_id, bundle in bundles.items()
        if bundle.elevation_attribute is not None
    }
    expected_surface_attributes = {edge_id: bundle.surface for edge_id, bundle in bundles.items()}
    expected_way_tags = {edge_id: bundle.way_tags for edge_id, bundle in bundles.items()}
    expected_stop_counts = {
        edge_id: bundle.attribute_counts.stop_count for edge_id, bundle in bundles.items()
        if bundle.attribute_counts is not None
    }
    expected_intersection_counts = {
        edge_id: bundle.attribute_counts.intersection_count for edge_id, bundle in bundles.items()
        if bundle.attribute_counts is not None
    }
    expected_accident_counts = {
        edge_id: bundle.attribute_counts.accident_count for edge_id, bundle in bundles.items()
        if bundle.attribute_counts is not None
    }
    expected_designated_edge_ids = {edge_id for edge_id, bundle in bundles.items() if bundle.is_designated}

    assert legacy.elevation_attributes == expected_elevation_attributes
    assert legacy.surface_attributes == expected_surface_attributes
    assert legacy.way_tags == expected_way_tags
    assert legacy.stop_counts == expected_stop_counts
    assert legacy.intersection_counts == expected_intersection_counts
    assert legacy.accident_counts == expected_accident_counts
    assert legacy.designated_edge_ids == expected_designated_edge_ids


def test_edge_material_table_getitem_and_values_mimic_dict_interface():
    bundles = {"e1": _full_bundle("e1"), "e2": _bare_bundle()}
    table = EdgeMaterialTable.from_bundles(list(bundles.keys()), bundles)

    assert table["e1"] == bundles["e1"]
    try:
        table["missing"]
        assert False, "KeyErrorを送出するはず"
    except KeyError:
        pass
    assert sorted(table.values(), key=lambda b: b.surface or "") == sorted(
        bundles.values(), key=lambda b: b.surface or ""
    )
