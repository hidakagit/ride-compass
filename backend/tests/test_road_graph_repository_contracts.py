"""`infrastructure/road_graph_repository.py`——DBを要さない契約。

対象は、道路網と材料の読み出しのうち**Python側が決めていること**:

- 地図のフィーチャーの鍵から、区間とwayのどちらの単位で読むか
- 逆向きに辿ったときの列の読み替え規則
- 材料の式が読む列を持つ表だけを結び、宣言に無い列を読む式を断ること
- 行から探索用グラフ・材料の行列を組む部分
- 取込範囲の外（None）と、範囲内で0件（空）の区別
- 路面タイルの材料の列を、どの材料についても値式から組むこと

ここで見ないもの:
- 材料の値式そのもの → `test_material_values.py`、欠損率 → `test_material_coverage.py`
- タイルの形の署名 → `test_cache_identity.py`
- 有向な枝の鍵の書式（`domain/graph.py`の持ち物。逆の`parse_edge_key`を持つので衝突しない）。向きで分かれる
  ことは、ここの両向きの取り直しが通す
- スキーマの作成（`create_tables`）と、SQLが実際に返す値

**セッションは差し替えて与える。** 実行した文とパラメータを記録するだけのフェイクを使い、
実在の道路id・タグ・列の値を持ち込まない。材料の列は`material_array_columns()`から導いて
選ぶ（idを名指ししない）。
"""

from types import SimpleNamespace

import numpy as np
import pytest
import shapely
from sqlalchemy import text

from app.domain.attributes import CategoricalColumn
from app.domain.graph import LeanEdge
from app.domain.hard_filters import hard_filter_columns
from app.domain.landcover import LandcoverPercentages, landcover_key
from app.domain.material_catalog import MATERIAL_CATALOG, material_array_columns, tile_column_sql
from app.domain.region import BoundingBox
from app.infrastructure import road_graph_repository
from app.infrastructure.derived_models import EdgeCountsRow, EdgeElevationRow, EdgeLandcoverRow, WayCountsRow
from app.domain.graph import edge_key, node_key
from app.services.axis_preview_service import SAMPLE_LIMIT, SAMPLE_PERCENT
from app.infrastructure.road_graph_repository import (
    ID_CHUNK_SIZE,
    MATERIAL_ARRAY_COLUMN_ORDER,
    RoadGraphRepository,
    material_from_clause,
    reversed_material_expression,
    way_from_clause,
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


# --- 逆向きの読み替え ---------------------------------------------------------


@pytest.mark.parametrize(("name", "expression"), [
    ("start_a", "m.end_a"),
    # 勾配は符号を返す
    ("a_grade", "-m.a_grade"),
    # 向きで変わらない列
    ("a_count", None),
])
def test_reversed_expression_swaps_paired_tokens_and_flips_grades(name, expression):
    assert reversed_material_expression(name) == expression


def test_reversing_twice_returns_to_the_original_column():
    """対が壊れると、逆向きの枝の標高が別の列から来る。列の一覧は宣言から導く。"""
    reversed_columns = {column.name: expression
                        for row in (EdgeCountsRow, EdgeElevationRow, EdgeLandcoverRow) for column in row.__table__.columns
                        if (expression := reversed_material_expression(column.name)) is not None}
    assert reversed_columns, "向きで変わる列が1つも無い"
    for name, expression in reversed_columns.items():
        partner = expression.lstrip("-").removeprefix("m.")
        back = reversed_material_expression(partner)
        assert back is not None
        assert back.lstrip("-").removeprefix("m.") == name
        assert back.startswith("-") == expression.startswith("-")


# --- 材料の列 -----------------------------------------------------------------


def test_material_array_columns_are_all_distinct():
    """材料と付随列の名前がぶつかると、片方の値がもう片方を上書きして列がずれる。"""
    assert len(set(MATERIAL_ARRAY_COLUMN_ORDER)) == len(MATERIAL_ARRAY_COLUMN_ORDER)


def test_material_tables_are_joined_only_for_the_columns_the_expressions_read():
    """使わないJOINを足すと、材料1件を引くだけの値列挙まで道の全件へ広がる。"""
    edge_column = next(column for column in EdgeCountsRow.__table__.columns if not column.primary_key)
    clause = material_from_clause([f"em.{edge_column.name}"], "k.osm_way_id", "k.segment_index")

    assert "JOIN" not in way_from_clause(["w.tags"])
    assert EdgeCountsRow.__tablename__ in clause
    assert EdgeElevationRow.__tablename__ not in clause
    assert WayCountsRow.__tablename__ not in clause


@pytest.mark.parametrize("alias", ["em", "wm"])
def test_an_expression_reading_an_undeclared_column_is_refused(alias):
    """SQLの実行まで気づかないと、その経路の読み出しが材料ぶん丸ごと落ちる。"""
    with pytest.raises(ValueError, match=f"{alias}.column_a"):
        material_from_clause([f"{alias}.column_a"], "k.osm_way_id", "k.segment_index")


# --- ジオメトリ付きの取り直し -------------------------------------------------


def _geometry_row(way_id=1, segment=0, coordinates=((139.0, 35.0), (139.1, 35.2))):
    return _Row(osm_way_id=way_id, segment_index=segment, from_node_id=1, to_node_id=2,
                distance_m=100.0, wkb=shapely.to_wkb(shapely.LineString(coordinates)))


async def test_both_directions_of_a_segment_share_one_row():
    """形は向きに依らず、逆向きは同じ行の形を逆順にし、端点を入れ替える。

    同じ区間を向きの数だけ引き直さないことは見ない——結果の辞書は引き直しても同じで、違いはDBの手間だけ
    （読むだけの問い合わせの引数になる）。理由は実装のコメントが持つ。"""
    repo, _ = _repo([_geometry_row()])
    requested = [_lean_edge(1, 0, True), _lean_edge(1, 0, False)]

    edges = await repo.get_edges_with_geometry(requested)

    forward = edges[edge_key(1, 0, True)]
    backward = edges[edge_key(1, 0, False)]
    assert forward.geometry == [[35.0, 139.0], [35.2, 139.1]]
    assert backward.geometry == [[35.2, 139.1], [35.0, 139.0]]
    assert (backward.from_node_id, backward.to_node_id) == (node_key(2), node_key(1))


def _lean_edge(way_id=1, segment=0, forward=True) -> LeanEdge:
    return LeanEdge(edge_id=edge_key(way_id, segment, forward),
                    from_node_id=node_key(1), to_node_id=node_key(2),
                    geometry=[], distance_m=100.0,
                    osm_way_id=way_id, segment_index=segment, forward=forward)


# --- 材料の行列 ---------------------------------------------------------------


def _arrays_row(count: int, values: dict[str, list] | None = None) -> _Row:
    """材料配列のクエリが返す1行。列は`c_<名前>`で、渡さない列は欠損で埋める。"""
    given = values or {}
    return _Row(**{f"c_{name}": list(given.get(name, [None] * count))
                   for name in MATERIAL_ARRAY_COLUMN_ORDER})


async def test_material_values_land_in_the_matrix_of_their_dtype():
    """分類を数値の行列へ混ぜられないため、数値と分類の2つに分かれる。真偽は数値の行列に1.0/0.0で載る。"""
    numeric_ids, categorical_ids = material_array_columns()
    boolean = next(m for m in numeric_ids if MATERIAL_CATALOG[m].dtype == "boolean")
    numeric = next(m for m in numeric_ids if MATERIAL_CATALOG[m].dtype == "numeric")
    assert categorical_ids, "分類の材料が無い"
    categorical = categorical_ids[0]
    repo, _ = _repo([_arrays_row(3, {numeric: [1.5, None, None], boolean: [True, False, None],
                                     categorical: ["value_a", None, None]})])

    arrays = await repo.get_edge_material_arrays([1, 1, 1], [0, 1, 2], [True, True, True], 5)

    assert arrays.columns()[numeric][0] == 1.5
    # 欠損は0ではなくNaN。0で埋めると「値が無い」が「一番良い値」として採点される。
    assert np.isnan(arrays.columns()[numeric][1])
    # 真偽の欠損（道の生データが無い区間）も、非該当（0.0）ではなく不明（NaN）。
    assert arrays.columns()[boolean][:2].tolist() == [1.0, 0.0]
    assert np.isnan(arrays.columns()[boolean][2])
    # 分類の材料は語彙への番号の列で、値へ戻すと行ごとの値（値なしはNone）になる。
    column = arrays.columns()[categorical]
    assert isinstance(column, CategoricalColumn)
    assert [column.value_at(row) for row in range(len(column))] == ["value_a", None, None]


async def test_hard_filter_flags_are_named_by_their_filter():
    """列が取り違うと、そのフィルタが常に「該当しない」になって黙って素通りする。"""
    names = hard_filter_columns()
    assert names, "0次ハードフィルタが1つも無い"
    repo, _ = _repo([_arrays_row(1, {f"hf_{names[0]}": [True]})])

    arrays = await repo.get_edge_material_arrays([1], [0], [True], 1)

    assert arrays.hard_filter_columns()[names[0]].tolist() == [True]


class _EchoingArraysSession:
    """材料配列のクエリに、受け取った区間をそのまま値として返すセッション（DBの`WITH ORDINALITY`の代わり）。
    way・区間の番号・向きを、それぞれ距離・獲得標高・標高の有無の列に入れる。"""

    async def execute(self, statement, params):
        count = len(params["way_ids"])
        return _Result([_arrays_row(count, {"distance_m": params["way_ids"],
                                            "elevation_gain_m": params["segment_indexes"],
                                            "elevation_present": params["forwards"]})])


async def test_rows_keep_the_order_of_the_given_edges_across_chunks():
    """並びは渡した区間の位置で決まる。1文に載る数を超えて分けても、1つでもずれると値が列の間で静かに入れ替わる。"""
    count = ID_CHUNK_SIZE + 1
    way_ids = list(range(count))
    segment_indexes = [i % 7 for i in way_ids]
    forwards = [i % 2 == 0 for i in way_ids]

    arrays = await RoadGraphRepository(_EchoingArraysSession()).get_edge_material_arrays(
        way_ids, segment_indexes, forwards, 1)

    assert arrays.distance_m.tolist() == way_ids
    assert arrays.elevation_gain_m.tolist() == segment_indexes
    assert arrays.elevation_present.tolist() == forwards


async def test_paired_edge_columns_are_not_swapped():
    """取り違えても型では落ちない対だけを見る（緯度と経度・登りと下り）。"""
    repo, _ = _repo([_arrays_row(1, {
        "mid_lat": [35.5], "mid_lon": [139.5],
        "elevation_gain_m": [2.0], "elevation_loss_m": [1.0],
    })])

    arrays = await repo.get_edge_material_arrays([1], [0], [True], 1)

    assert (arrays.mid_lat[0], arrays.mid_lon[0]) == (35.5, 139.5)
    assert (arrays.elevation_gain_m[0], arrays.elevation_loss_m[0]) == (2.0, 1.0)


# --- way粒度の読み出し --------------------------------------------------------


async def test_way_is_looked_up_by_its_key_as_text():
    """道の生データの主キー（`source_features.natural_key`）はtext。数で渡すと1件も当たらず、
    区間インスペクタが常に空になる。"""
    repo, session = _repo([_Row(m_material_a=1.0)],
                          [_Row(highway="highway_a", tags={"tag_a": "value_a"})])

    await repo.get_way_material_values(123, 1)
    await repo.get_way_tags_by_osm_way_id(123)

    assert [params["osm_way_id"] for params in session.params] == ["123", "123"]


async def test_unknown_way_has_neither_materials_nor_tags():
    repo, _ = _repo([], [])

    assert await repo.get_way_material_values(123, 1) is None
    assert await repo.get_way_tags_by_osm_way_id(123) is None


async def test_sampled_way_without_length_is_dropped():
    """延長は分布の重み。0を混ぜると、その材料の値が重みなしで平均へ入る。"""
    repo, _ = _repo([_Row(length_m=0.0, m_material_a=1.0),
                     _Row(length_m=10.0, m_material_a=2.0)])

    samples = await repo.sample_way_material_values(1, SAMPLE_PERCENT, SAMPLE_LIMIT, None)

    assert samples == [(10.0, {"material_a": 2.0})]


async def test_distinct_values_are_listed_only_for_categorical_materials(monkeypatch):
    """取りうる値の一覧に意味があるのは分類の材料だけ。値の求め方はカタログの宣言が唯一持つ。"""
    monkeypatch.setattr(road_graph_repository, "MATERIAL_CATALOG", {
        "material_a": SimpleNamespace(value_sql="w.tags->>'tag_a'", dtype="categorical"),
        "material_b": SimpleNamespace(value_sql="w.tags->>'tag_b'", dtype="numeric"),
        "material_c": SimpleNamespace(value_sql=None, dtype="categorical"),
    })
    repo, _ = _repo([_Row(value="value_a"), _Row(value="value_b")])

    assert await repo.get_distinct_material_values("material_a") == ["value_a", "value_b"]
    assert await repo.get_distinct_material_values("material_b") == []
    assert await repo.get_distinct_material_values("material_c") == []
    assert await repo.get_distinct_material_values("material_unknown") == []


# --- 事故の収録年 -------------------------------------------------------------


@pytest.mark.parametrize(("declared", "years"), [([2023, 2021, 2022], [2021, 2022, 2023]), (None, [])])
async def test_accident_years_come_from_the_declared_profile(declared, years):
    """実データの発生年を数えない——事故が1件も無かった年が落ちて、密度の分母がずれる。"""
    repo, _ = _repo([_Row(years=declared)])

    assert await repo.get_accident_years() == years


# --- 土地被覆の内訳 -----------------------------------------------------------


def _landcover_row(valid_pixels: int | None = 100) -> _Row:
    """表が入れる形の行。割合は有効画素が正の行だけが持つ。"""
    values: dict[str, object] = {"lc_valid_pixels": valid_pixels}
    for name in LandcoverPercentages.model_fields:
        values[f"lc_{landcover_key(name)}"] = 12.5 if valid_pixels else None
    return _Row(**values)


@pytest.mark.parametrize(("feature_key", "segment_index"), [
    ("123-4", 4),
    # タイルは区間とway丸ごとを同じ名前の鍵で出す。区切りの無い鍵はway丸ごと
    ("123", None),
    # 鍵とwayが食い違うのは呼び出し側の取り違え。別の区間の内訳を返すよりway全体で答える
    ("456-7", None),
    # 鍵はフロントから来る。数でない鍵を区間として扱うと、引き直しが例外で落ちる
    ("123-x", None),
])
async def test_landcover_is_read_at_the_unit_the_map_paints(feature_key, segment_index):
    """鍵が区間を指すなら区間の値。way丸ごとの値を返すと、同じ場所で地図の色と数字が食い違う。"""
    repo, session = _repo([_landcover_row()])

    await repo.get_feature_landcover(123, feature_key)

    assert session.params[0].get("segment_index") == segment_index


async def test_incomplete_landcover_is_not_reported():
    """値が無い・有効画素が足りなかった区間で0%と答えると、内訳が「すべて未分類」に見える。"""
    repo, _ = _repo([_landcover_row(valid_pixels=None)])

    assert await repo.get_feature_landcover(123, None) is None


# --- タイル -------------------------------------------------------------------

# タイル1枚を焼く口。路面の口はこの口へSQLを渡すだけ。SQLはフェイクのセッションが実行しない。
def _read_mvt(repo):
    return repo.get_tile_mvt(text("SELECT 1"), "layer", 14, 1, 2, BBOX)


_TILE_READERS = {
    "mvt": _read_mvt,
    "midpoints": lambda repo: repo.get_feature_midpoints_in_tile(14, 1, 2, BBOX),
    "gradient_inputs": lambda repo: repo.get_feature_gradient_inputs_in_tile(14, 1, 2, BBOX),
}


@pytest.mark.parametrize("read", _TILE_READERS.values(), ids=_TILE_READERS)
async def test_outside_the_imported_area_nothing_is_returned(read):
    """取込範囲外（None）と、範囲内で対象0件（空）を区別する。利用側の見せ方が変わる。"""
    repo, _ = _repo([_Row(covered=False, payload=None)])

    assert await read(repo) is None


@pytest.mark.parametrize(("tile", "payload"), [
    # 長さ0のバイト列は「featureが1つも無い有効なMVT」として地図がそのまま受理する
    (None, b""),
    (memoryview(b"tile_a"), b"tile_a"),
])
async def test_tile_inside_the_imported_area_is_bytes_even_without_features(tile, payload):
    repo, _ = _repo([_Row(covered=True, tile=tile)])

    assert await _read_mvt(repo) == payload


def test_every_material_on_the_road_tile_is_baked_from_its_value_expression():
    """地図の色と評価は、同じ材料なら同じ求め方から出る。タイルの列を手で書くと、値式を直しても地図だけが
    古い求め方のまま残る。"""
    sql = str(road_graph_repository.ROAD_SURFACE_TILE_MVT_SQL)
    on_tile = [spec for spec in MATERIAL_CATALOG.values() if spec.tile_property is not None]

    assert on_tile
    for spec in on_tile:
        column = tile_column_sql(spec)
        assert f"({spec.value_sql})" in column, spec.material_id
        assert f"{column} AS {spec.tile_property}" in sql, spec.material_id


async def test_feature_keys_are_returned_as_text():
    """鍵はタイルが焼いたものと同じ文字列で配る。数で配ると、フロントのidと噛み合わず
    色が一切付かない。"""
    repo, _ = _repo([_Row(covered=True, midpoints=None)],
                    [_Row(covered=True, midpoints={123: [35.1, 139.2], "123-4": [35, 139]})])

    assert await repo.get_feature_midpoints_in_tile(14, 1, 2, BBOX) == {}
    assert await repo.get_feature_midpoints_in_tile(14, 1, 2, BBOX) == {
        "123": (35.1, 139.2), "123-4": (35.0, 139.0)}


async def test_gradient_inputs_are_pairs_of_numbers():
    repo, _ = _repo([_Row(covered=True, inputs=None)],
                    [_Row(covered=True, inputs={"123-4": [3, 90]})])

    assert await repo.get_feature_gradient_inputs_in_tile(14, 1, 2, BBOX) == {}
    assert await repo.get_feature_gradient_inputs_in_tile(14, 1, 2, BBOX) == {"123-4": (3.0, 90.0)}
