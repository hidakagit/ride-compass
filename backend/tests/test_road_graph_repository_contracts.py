"""`infrastructure/road_graph_repository.py`——DBを要さない契約。

対象は、道路網と材料の読み出しのうち**Python側が決めていること**:

- 鍵（ノード・有向な枝・タイルのフィーチャー）の作り方と読み方
- 逆向きに辿ったときの列の読み替え規則
- 行から探索用グラフ・材料の行列を組む部分
- 取込範囲の外（None）と、範囲内で0件（空）の区別

ここで見ないもの:
- 材料の値式そのもの → `test_material_values.py`、欠損率 → `test_material_coverage.py`
- タイルの形の署名 → `test_cache_identity.py`
- スキーマの作成（`create_tables`）と、SQLが実際に返す値

**セッションは差し替えて与える。** 実行した文とパラメータを記録するだけのフェイクを使い、
実在の道路id・タグ・列の値を持ち込まない。材料の列は`material_array_columns()`から導いて
選ぶ（idを名指ししない）。
"""

from types import SimpleNamespace

import numpy as np
import pytest
import shapely

from app.domain.graph import LeanEdge
from app.domain.hard_filters import hard_filter_columns
from app.domain.landcover import LandcoverPercentages
from app.domain.material_catalog import material_array_columns
from app.domain.region import BoundingBox
from app.infrastructure import road_graph_repository
from app.infrastructure.road_graph_repository import (
    MATERIAL_ARRAY_COLUMN_ORDER,
    RoadGraphRepository,
    _REVERSED_ELEVATION_COLUMNS,
    _SAMPLE_WAY_MATERIAL_VALUES_IN_BBOX_SQL,
    _SAMPLE_WAY_MATERIAL_VALUES_SQL,
    _way_from_clause,
    edge_key,
    node_key,
    parse_edge_feature_key,
    reversed_material_expression,
)

BBOX = BoundingBox(min_latitude=35.0, min_longitude=139.0,
                   max_latitude=35.1, max_longitude=139.1)


class _Row:
    """DBの1行。属性・位置・`_mapping`のどれでも読める（読み出し側が3通り使う）。"""

    def __init__(self, **values):
        self._mapping = dict(values)
        self.__dict__.update(values)

    def __iter__(self):
        return iter(self._mapping.values())


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def one(self):
        (row,) = self._rows
        return row

    def scalar(self):
        return next(iter(self._rows[0])) if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    """`execute`だけを持つセッション。呼ばれた順に用意した行を返し、文とパラメータを残す。"""

    def __init__(self, *results):
        self._results = list(results)
        self.calls: list[tuple[object, dict | None]] = []

    async def execute(self, statement, params=None):
        self.calls.append((statement, params))
        return _Result(self._results.pop(0))

    @property
    def params(self) -> list[dict | None]:
        return [params for _, params in self.calls]


def _repo(*results) -> tuple[RoadGraphRepository, _FakeSession]:
    session = _FakeSession(*results)
    return RoadGraphRepository(session), session


# --- 鍵 ---------------------------------------------------------------------


def test_feature_key_of_a_whole_way_has_no_segment():
    """タイルは区間とway丸ごとを同じ名前の鍵で出す。読む側は区切りの有無だけで見分ける。"""
    assert parse_edge_feature_key("123-4") == (123, 4)
    assert parse_edge_feature_key("123") is None


def test_unparsable_feature_key_is_not_a_segment():
    """鍵はフロントから来る。数でない鍵を区間として扱うと、引き直しが例外で落ちる。"""
    assert parse_edge_feature_key("123-x") is None
    assert parse_edge_feature_key("123-") is None
    assert parse_edge_feature_key("-4") is None


def test_edge_keys_never_collide():
    """衝突すると、後から組んだ枝が前のものを辞書から追い出す（片方向が黙って消える）。"""
    triples = [(1, 0, True), (1, 0, False), (1, 1, True), (2, 0, True)]
    assert len({edge_key(*triple) for triple in triples}) == len(triples)


# --- 逆向きの読み替え ---------------------------------------------------------


def test_paired_tokens_are_swapped_in_both_directions():
    assert reversed_material_expression("start_a") == "m.end_a"
    assert reversed_material_expression("end_a") == "m.start_a"
    assert reversed_material_expression("a_gain_b") == "m.a_loss_b"
    assert reversed_material_expression("a_loss_b") == "m.a_gain_b"
    assert reversed_material_expression("max_a") == "m.min_a"
    assert reversed_material_expression("min_a") == "m.max_a"


def test_grade_flips_its_sign():
    assert reversed_material_expression("a_grade") == "-m.a_grade"
    assert reversed_material_expression("max_grade") == "-m.min_grade"


def test_direction_independent_column_has_no_reversed_expression():
    assert reversed_material_expression("a_count") is None


def test_only_the_first_pair_and_the_first_occurrence_are_swapped():
    """2度入れ替えると元へ戻り、逆向きの枝が順向きと同じ値を読む。"""
    assert reversed_material_expression("start_max_a") == "m.end_max_a"
    assert reversed_material_expression("start_a_start") == "m.end_a_start"


def test_reversing_twice_returns_to_the_original_column():
    """対が壊れると、逆向きの枝の標高が別の列から来る。列の一覧は宣言から導く。"""
    assert _REVERSED_ELEVATION_COLUMNS, "向きで変わる列が1つも無い"
    for name, expression in _REVERSED_ELEVATION_COLUMNS.items():
        partner = expression.lstrip("-").removeprefix("m.")
        back = reversed_material_expression(partner)
        assert back is not None
        assert back.lstrip("-").removeprefix("m.") == name
        assert back.startswith("-") == expression.startswith("-")


# --- 材料の列 -----------------------------------------------------------------


def test_material_array_columns_are_all_distinct():
    """材料と付随列の名前がぶつかると、片方の値がもう片方を上書きして列がずれる。"""
    assert len(set(MATERIAL_ARRAY_COLUMN_ORDER)) == len(MATERIAL_ARRAY_COLUMN_ORDER)


def test_way_from_clause_joins_only_what_the_expression_reads():
    """使わないJOINを足すと、材料1件を引くだけの値列挙まで道の全件へ広がる。"""
    assert "JOIN" not in _way_from_clause(["w.tags"])
    assert _way_from_clause(["em.a"]).count("JOIN") == 1
    assert _way_from_clause(["em.a", "wm.b", "re.c"]).count("JOIN") == 3


# --- 行からグラフを組む -------------------------------------------------------


def _edge_row(way_id=1, segment=0, from_node=1, to_node=2, direction=None):
    return _Row(osm_way_id=way_id, segment_index=segment,
                from_node_id=from_node, to_node_id=to_node,
                distance_m=100.0, bearing_deg=10.0, reverse_bearing_deg=190.0,
                highway="highway_a", direction=direction)


def _node_row(osm_node_id):
    return _Row(osm_node_id=osm_node_id, longitude=139.0, latitude=35.0,
                has_traffic_signals=False, max_highway_rank=0)


async def test_two_way_segment_becomes_two_directed_edges():
    """DBの区間は向きを持たない1行で、有向の枝はここだけが作る。"""
    repo, _ = _repo([_edge_row(direction="both")], [_node_row(1), _node_row(2)])

    graph = await repo.get_graph_topology_in_bbox(BBOX)

    forward = graph.edges[edge_key(1, 0, True)]
    backward = graph.edges[edge_key(1, 0, False)]
    assert (forward.from_node_id, forward.to_node_id) == (node_key(1), node_key(2))
    assert (backward.from_node_id, backward.to_node_id) == (node_key(2), node_key(1))
    assert (forward.bearing_deg, backward.bearing_deg) == (10.0, 190.0)
    assert forward.geometry == [] and backward.geometry == []
    assert set(graph.nodes) == {node_key(1), node_key(2)}


@pytest.mark.parametrize(("direction", "travellable"), [("forward", True), ("backward", False)])
async def test_one_way_keeps_only_the_travellable_direction(direction, travellable):
    """逆走する枝を作ると、通れない向きの経路を候補として出す。"""
    repo, _ = _repo([_edge_row(direction=direction)], [_node_row(1), _node_row(2)])

    graph = await repo.get_graph_topology_in_bbox(BBOX)

    assert list(graph.edges) == [edge_key(1, 0, travellable)]


async def test_edge_whose_endpoint_is_missing_is_dropped():
    """端のノードが無い枝を残すと、探索が存在しないノードを辿って落ちる。"""
    repo, _ = _repo([_edge_row()], [_node_row(1)])

    graph = await repo.get_graph_topology_in_bbox(BBOX)

    assert graph.edges == {}


async def test_no_edges_in_bbox_yields_no_graph():
    """道路が1本も無ければノードも引かない（呼び出し側は候補なしとして扱う）。"""
    repo, session = _repo([])

    assert await repo.get_graph_topology_in_bbox(BBOX) is None
    assert len(session.calls) == 1


async def test_endpoint_nodes_are_looked_up_as_text_in_chunks(monkeypatch):
    """`source_features.natural_key`はtext。数で渡すと1件も一致せず、枝が全部落ちる。"""
    monkeypatch.setattr(road_graph_repository, "_ID_CHUNK_SIZE", 2)
    repo, session = _repo(
        [_edge_row(from_node=1, to_node=2), _edge_row(segment=1, from_node=2, to_node=3)],
        [_node_row(1), _node_row(2)],
        [_node_row(3)],
    )

    await repo.get_graph_topology_in_bbox(BBOX)

    assert [params["node_keys"] for params in session.params[1:]] == [["1", "2"], ["3"]]


# --- ジオメトリ付きの取り直し -------------------------------------------------


def _geometry_row(way_id=1, segment=0, coordinates=((139.0, 35.0), (139.1, 35.2))):
    return _Row(osm_way_id=way_id, segment_index=segment, from_node_id=1, to_node_id=2,
                distance_m=100.0, bearing_deg=10.0, reverse_bearing_deg=190.0,
                wkb=shapely.to_wkb(shapely.LineString(coordinates)))


async def test_geometry_is_not_fetched_for_an_empty_request():
    repo, session = _repo()

    assert await repo.get_edges_with_geometry([]) == {}
    assert session.calls == []


async def test_both_directions_of_a_segment_share_one_row():
    """同じ区間を向きの数だけ引き直さない。形は向きに依らず、逆順にすれば足りる。"""
    repo, session = _repo([_geometry_row()])
    requested = [_lean_edge(1, 0, True), _lean_edge(1, 0, False)]

    edges = await repo.get_edges_with_geometry(requested)

    assert session.params[0]["way_ids"] == [1]
    assert session.params[0]["segment_indexes"] == [0]
    forward = edges[edge_key(1, 0, True)]
    backward = edges[edge_key(1, 0, False)]
    assert forward.geometry == [[35.0, 139.0], [35.2, 139.1]]
    assert backward.geometry == [[35.2, 139.1], [35.0, 139.0]]
    assert (backward.from_node_id, backward.to_node_id) == (node_key(2), node_key(1))
    assert backward.bearing_deg == 190.0


# --- 材料の行列 ---------------------------------------------------------------


def _lean_edge(way_id=1, segment=0, forward=True) -> LeanEdge:
    return LeanEdge(edge_id=edge_key(way_id, segment, forward),
                    from_node_id=node_key(1), to_node_id=node_key(2),
                    geometry=[], distance_m=100.0,
                    osm_way_id=way_id, segment_index=segment, forward=forward)


def _arrays_row(count: int, values: dict[str, list] | None = None) -> _Row:
    """材料配列のクエリが返す1行。列は`c_<名前>`で、渡さない列は欠損で埋める。"""
    given = values or {}
    return _Row(**{f"c_{name}": list(given.get(name, [None] * count))
                   for name in MATERIAL_ARRAY_COLUMN_ORDER})


async def test_material_values_land_in_the_matrix_of_their_dtype():
    """真偽と分類を数値の行列へ混ぜられないため、dtypeで3つに分かれる。"""
    numeric_ids, boolean_ids, categorical_ids = material_array_columns()
    assert numeric_ids and boolean_ids and categorical_ids, "dtypeごとの材料が揃っていない"
    numeric, boolean, categorical = numeric_ids[0], boolean_ids[0], categorical_ids[0]
    repo, _ = _repo([_arrays_row(2, {numeric: [1.5, None], boolean: [True, None],
                                     categorical: ["value_a", "value_a"]})])

    arrays = await repo.get_edge_material_arrays([_lean_edge(), _lean_edge(segment=1)], 5)

    assert arrays.column(numeric)[0] == 1.5
    # 欠損は0ではなくNaN。0で埋めると「値が無い」が「一番良い値」として採点される。
    assert np.isnan(arrays.column(numeric)[1])
    assert arrays.column(boolean).tolist() == [True, False]
    first, second = arrays.column(categorical)
    assert first == "value_a"
    # 同じ文字列は1つのオブジェクトを指す（pickleが重複を省き、ディスクの実体が縮む）。
    assert first is second


async def test_hard_filter_flags_are_named_by_their_filter():
    """列が取り違うと、そのフィルタが常に「該当しない」になって黙って素通りする。"""
    names = hard_filter_columns()
    assert names, "0次ハードフィルタが1つも無い"
    repo, _ = _repo([_arrays_row(1, {f"hf_{names[0]}": [True]})])

    arrays = await repo.get_edge_material_arrays([_lean_edge()], 1)

    assert arrays.hard_filter_columns()[names[0]].tolist() == [True]


async def test_rows_keep_the_order_of_the_given_edges_across_chunks(monkeypatch):
    """並びは渡した枝の位置で決まる。1つでもずれると値が列の間で静かに入れ替わる。"""
    monkeypatch.setattr(road_graph_repository, "_ID_CHUNK_SIZE", 1)
    repo, session = _repo([_arrays_row(1, {"distance_m": [10.0]})],
                          [_arrays_row(1, {"distance_m": [20.0]})])
    edges = [_lean_edge(1, 0, True), _lean_edge(2, 3, False)]

    arrays = await repo.get_edge_material_arrays(edges, 1)

    assert arrays.edge_ids == [edge.edge_id for edge in edges]
    assert arrays.distance_m.tolist() == [10.0, 20.0]
    assert [params["way_ids"] for params in session.params] == [[1], [2]]
    assert [params["segment_indexes"] for params in session.params] == [[0], [3]]
    assert [params["forwards"] for params in session.params] == [[True], [False]]


async def test_paired_edge_columns_are_not_swapped():
    """取り違えても型では落ちない対だけを見る（緯度と経度・始点と終点・登りと下り）。"""
    repo, _ = _repo([_arrays_row(1, {
        "mid_lat": [35.5], "mid_lon": [139.5],
        "elevation_start_m": [5.0], "elevation_end_m": [7.0],
        "elevation_gain_m": [2.0], "elevation_loss_m": [1.0],
        "elevation_max_grade": [3.0], "elevation_min_grade": [-4.0],
    })])

    arrays = await repo.get_edge_material_arrays([_lean_edge()], 1)

    assert (arrays.mid_lat[0], arrays.mid_lon[0]) == (35.5, 139.5)
    assert (arrays.elevation_start_m[0], arrays.elevation_end_m[0]) == (5.0, 7.0)
    assert (arrays.elevation_gain_m[0], arrays.elevation_loss_m[0]) == (2.0, 1.0)
    assert (arrays.elevation_max_grade[0], arrays.elevation_min_grade[0]) == (3.0, -4.0)


# --- way粒度の読み出し --------------------------------------------------------


async def test_way_is_looked_up_by_its_key_as_text():
    """道の生データの主キー（`source_features.natural_key`）はtext。数で渡すと1件も当たらず、
    区間インスペクタが常に空になる。"""
    repo, session = _repo([_Row(m_material_a=1.0)],
                          [_Row(highway="highway_a", tags={"tag_a": "value_a"}, surface=None)])

    await repo.get_way_material_values(123, 1)
    await repo.get_way_tags_by_osm_way_id(123)

    assert [params["osm_way_id"] for params in session.params] == ["123", "123"]


async def test_unknown_way_has_neither_materials_nor_tags():
    repo, _ = _repo([], [])

    assert await repo.get_way_material_values(123, 1) is None
    assert await repo.get_way_tags_by_osm_way_id(123) is None


async def test_way_without_tags_reads_as_an_empty_mapping():
    """タグの無い道でも、読む側は辞書として引ける（Noneを配ると呼び出し側が落ちる）。"""
    repo, _ = _repo([_Row(highway=None, tags=None, surface=None)])

    assert await repo.get_way_tags_by_osm_way_id(123) == (None, {}, None)


async def test_a_range_replaces_the_sampling():
    """`TABLESAMPLE`は表全体のページから抽選するため、狭い範囲と重ねると標本が数本へ落ちる。"""
    repo, session = _repo([], [])

    await repo.sample_way_material_values(1)
    await repo.sample_way_material_values(1, bbox=BBOX)

    assert session.calls[0][0] is _SAMPLE_WAY_MATERIAL_VALUES_SQL
    assert "sample_percent" in session.params[0]
    assert session.calls[1][0] is _SAMPLE_WAY_MATERIAL_VALUES_IN_BBOX_SQL
    assert "sample_percent" not in session.params[1]
    assert session.params[1]["xmin"] == BBOX.min_longitude


@pytest.mark.parametrize("length_m", [None, 0.0])
async def test_sampled_way_without_length_is_dropped(length_m):
    """延長は分布の重み。0を混ぜると、その材料の値が重みなしで平均へ入る。"""
    repo, _ = _repo([_Row(length_m=length_m, m_material_a=1.0),
                     _Row(length_m=10.0, m_material_a=2.0)])

    samples = await repo.sample_way_material_values(1)

    assert samples == [(10.0, {"material_a": 2.0})]


async def test_distinct_values_are_listed_only_for_categorical_materials(monkeypatch):
    """取りうる値の一覧に意味があるのは分類の材料だけ。値の求め方はカタログの宣言が唯一持つ。"""
    monkeypatch.setattr(road_graph_repository, "MATERIAL_CATALOG", {
        "material_a": SimpleNamespace(value_sql="w.tags->>'tag_a'", dtype="categorical"),
        "material_b": SimpleNamespace(value_sql="w.tags->>'tag_b'", dtype="numeric"),
        "material_c": SimpleNamespace(value_sql=None, dtype="categorical"),
    })
    repo, session = _repo([_Row(value="value_a"), _Row(value="value_b")])

    assert await repo.get_distinct_material_values("material_a") == ["value_a", "value_b"]
    assert await repo.get_distinct_material_values("material_b") == []
    assert await repo.get_distinct_material_values("material_c") == []
    assert await repo.get_distinct_material_values("material_unknown") == []
    assert len(session.calls) == 1


# --- 事故の収録年 -------------------------------------------------------------


async def test_accident_years_come_from_the_declared_profile():
    """実データの発生年を数えない——事故が1件も無かった年が落ちて、密度の分母がずれる。"""
    repo, _ = _repo([_Row(years=[2023, 2021, 2022])])

    assert await repo.get_accident_years() == [2021, 2022, 2023]


async def test_no_accident_profile_yields_no_years():
    repo, _ = _repo([_Row(years=None)])

    assert await repo.get_accident_years() == []


# --- 土地被覆の内訳 -----------------------------------------------------------


def _landcover_row(valid_pixels=100, missing: str | None = None) -> _Row:
    values: dict[str, object] = {"lc_valid_pixels": valid_pixels}
    for name in LandcoverPercentages.model_fields:
        if name.endswith("_percent"):
            values[f"lc_{name.removesuffix('_percent')}"] = None if name == missing else 12.5
    return _Row(**values)


async def test_landcover_is_read_at_the_unit_the_map_paints():
    """鍵が区間を指すなら区間の値。way丸ごとの値を返すと、同じ場所で地図の色と数字が食い違う。"""
    repo, session = _repo([_landcover_row()], [_landcover_row()])

    await repo.get_feature_landcover(123, "123-4")
    await repo.get_feature_landcover(123, "123")

    assert session.params[0]["segment_index"] == 4
    assert "segment_index" not in session.params[1]


async def test_landcover_of_a_key_from_another_way_falls_back_to_the_way():
    """鍵とwayが食い違うのは呼び出し側の取り違え。別の区間の内訳を返すよりway全体で答える。"""
    repo, session = _repo([_landcover_row()])

    await repo.get_feature_landcover(123, "456-7")

    assert "segment_index" not in session.params[0]


@pytest.mark.parametrize("row", [None, _landcover_row(valid_pixels=None),
                                 _landcover_row(missing="water_percent")])
async def test_incomplete_landcover_is_not_reported(row):
    """画素が無い・割合が欠けている区間で0%と答えると、内訳が「すべて未分類」に見える。"""
    repo, _ = _repo([] if row is None else [row])

    assert await repo.get_feature_landcover(123, None) is None


# --- タイル -------------------------------------------------------------------

_TILE_METHODS = ("get_road_surface_tile_mvt", "get_poi_tile_mvt",
                 "get_feature_keys_in_tile", "get_feature_gradient_inputs_in_tile")


@pytest.mark.parametrize("method", _TILE_METHODS)
async def test_outside_the_imported_area_nothing_is_returned(method):
    """取込範囲外（None）と、範囲内で対象0件（空）を区別する。利用側の見せ方が変わる。"""
    repo, _ = _repo([_Row(covered=False, payload=None)])

    assert await getattr(repo, method)(14, 1, 2, BBOX) is None


@pytest.mark.parametrize("method", ("get_road_surface_tile_mvt", "get_poi_tile_mvt"))
async def test_tile_without_features_is_an_empty_but_valid_tile(method):
    """長さ0のバイト列は「featureが1つも無い有効なMVT」として地図がそのまま受理する。"""
    repo, _ = _repo([_Row(covered=True, tile=None)])

    assert await getattr(repo, method)(14, 1, 2, BBOX) == b""


@pytest.mark.parametrize("method", ("get_road_surface_tile_mvt", "get_poi_tile_mvt"))
async def test_tile_payload_is_returned_as_bytes(method):
    repo, _ = _repo([_Row(covered=True, tile=memoryview(b"tile_a"))])

    assert await getattr(repo, method)(14, 1, 2, BBOX) == b"tile_a"


async def test_feature_keys_are_returned_as_text():
    """鍵はタイルが焼いたものと同じ文字列で配る。数で配ると、フロントのidと噛み合わず
    色が一切付かない。"""
    repo, _ = _repo([_Row(covered=True, feature_keys=None)],
                    [_Row(covered=True, feature_keys=[123, "123-4"])])

    assert await repo.get_feature_keys_in_tile(14, 1, 2, BBOX) == []
    assert await repo.get_feature_keys_in_tile(14, 1, 2, BBOX) == ["123", "123-4"]


async def test_gradient_inputs_are_pairs_of_numbers():
    repo, _ = _repo([_Row(covered=True, inputs=None)],
                    [_Row(covered=True, inputs={"123-4": [3, 90]})])

    assert await repo.get_feature_gradient_inputs_in_tile(14, 1, 2, BBOX) == {}
    assert await repo.get_feature_gradient_inputs_in_tile(14, 1, 2, BBOX) == {"123-4": (3.0, 90.0)}
