"""材料の値を求めるSQLの式が、入力に対して返す値。

式の部品は`domain/material_sql.py`、材料ごとの式はカタログ（`domain/material_catalog.py: material_value_sql`）が持つ。
SQLの中の条件はPythonのカバレッジに現れないので、式をテスト用DBで評価して値を見る。

入力の作り方:
- 道（別名`w`）: 道を取込の入口（`tests/source_ingest.py`）から入れ、読み手と同じ副問い合わせ
  （`infrastructure/source_models.py: WAYS_SOURCE_SQL`）で読む。
- 区間（`re`）・区間の値（`em`）: 派生の段が書く表の行の型（`road_edges`・`edge_materials`）で値を与える。
  値そのものの出し方（件数を数える等）は派生の段の責務なので、ここでは作らない。

部品の節は架空のタグ・路面の区分で、タイルへの載せ方の節は架空の材料で確かめる。カタログの節だけは、カタログに直に書かれた式（部品を使わないもの）を
本物の材料のidで引く——そこでは、その材料が何を返すかがテストの関心である。

カタログの全部の式が、読み出しの各経路（`infrastructure/road_graph_repository.py: RoadGraphRepository`の区間の材料・
道1本・道の標本・値の一覧・路面タイル）の中で実在の列だけを読むことも見る。上の節は別名を値で与えるので、
綴りの合わない列や、経路に無い別名を読む式を見つけられない。値の一覧の経路は、SQLが値を重ねず・値の無い道を除き・
並べることも、道の標本の経路は、範囲を絞ると抽選しないことも見る（セッションを差し替える契約のテストには、SQLが返す値が現れない）。

ここで見ないもの:
- 読み出しの経路が結果をどの形に並べるか（列と材料の対応・取込範囲の外のタイル） → `test_road_graph_repository_contracts.py`
- 欠損率の集計 → `test_material_coverage.py`
- 部品をどの材料がどのタグで使うか（カタログの宣言） → 宣言そのもので、テストに書き写さない
"""

import json

import pytest
from sqlalchemy import text

from app.domain import material_sql
from app.domain.material_catalog import (
    ACCIDENT_COUNT_PER_KM_YEAR,
    CoverageExcluded,
    MaterialSpec,
    TileEncoding,
    material_value_sql,
    tile_column_sql,
)
from app.domain.region import BoundingBox
from app.domain.road import SurfaceClass, TrackGrade
from app.infrastructure.source_models import WAYS_SOURCE_SQL
from tests.source_ingest import ingest_records, way_record

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


async def _ingest_ways(tags_by_way: dict[int, dict[str, str]]) -> None:
    """道ごとのタグで道を取り込む。"""
    await ingest_records("osm_way", [
        way_record(way_id, [(139.70, 35.68 + 0.001 * way_id), (139.701, 35.68 + 0.001 * way_id)],
                   [way_id * 10, way_id * 10 + 1], tags)
        for way_id, tags in tags_by_way.items()])


async def _way_values(session, expression: str, tags_by_way: dict[int, dict[str, str]]) -> dict[int, object]:
    """道ごとのタグで道を取り込み、式を道ごとに評価する。"""
    await _ingest_ways(tags_by_way)
    rows = await session.execute(text(f"SELECT w.osm_way_id, ({expression}) FROM {WAYS_SOURCE_SQL} w"))
    return dict(rows.all())


async def _edge_value(session, expression: str, *, distance_m: float, accident_years: int = 1,
                      **edge_materials: float | None) -> object:
    """区間の長さと区間の値を与えて、式を1区間ぶん評価する。"""
    row = await session.execute(
        text(f"SELECT ({expression})"
             " FROM json_populate_record(NULL::road_edges, CAST(:re AS json)) re,"
             " json_populate_record(NULL::edge_materials, CAST(:em AS json)) em"),
        {"re": json.dumps({"distance_m": distance_m}), "em": json.dumps(edge_materials),
         "accident_years": accident_years})
    return row.scalar_one()


# --- 部品（domain/material_sql.py） ---------------------------------------------------


@pytest.mark.parametrize(("tag", "expected"), [
    (" 60 ", 60),
    ("40.7", 40),  # 小数は切り捨てる
    ("0.5", None),  # 切り捨てると0
    ("50 mph", None),
])
async def test_a_number_tag_has_a_value_only_when_it_is_a_positive_number(road_graph_session, tag, expected):
    values = await _way_values(road_graph_session, material_sql.positive_integer_tag_sql("tag_a"),
                               {1: {} if tag is None else {"tag_a": tag}})

    assert values == {1: expected}


_CLASSES = (
    SurfaceClass("class_a", "区分A", {"value_a": "A", "o'quoted": "引用符"}, "speed.crr"),
    SurfaceClass("class_b", "区分B", {"value_b": "B"}, "speed.crr"),
    SurfaceClass("class_empty", "タグの無い区分", {}, "speed.crr"),
)
_GRADES = (
    TrackGrade("grade_a", "等級A", "class_b", "説明"),
)


async def test_a_surface_falls_in_the_class_that_lists_it_and_other_values_in_other(road_graph_session):
    values = await _way_values(road_graph_session, material_sql.surface_class_sql(_CLASSES), {
        1: {"surface": " VALUE_A "},
        2: {"surface": "o'quoted"},
        3: {"surface": "value_b"},
        4: {"surface": "unlisted"},
        5: {},
    })

    assert values == {1: "class_a", 2: "class_a", 3: "class_b", 4: material_sql.SURFACE_OTHER_KEY, 5: None}


async def test_the_surface_estimate_gives_every_road_a_value(road_graph_session):
    unknown_track = material_sql.UNKNOWN_TRACK_SURFACE.key
    unknown_road = material_sql.UNKNOWN_ROAD_SURFACE.key
    track = {"highway": material_sql.TRACK_HIGHWAY}

    values = await _way_values(road_graph_session, material_sql.surface_estimate_sql(_CLASSES, _GRADES), {
        # surfaceの区分が等級に先立つ。
        1: {**track, "surface": "value_a", "tracktype": "grade_a"},
        # 区分に無いsurfaceは、等級があれば等級から写す。
        2: {**track, "surface": "unlisted", "tracktype": " GRADE_A "},
        3: {"surface": "unlisted"},
        4: track,
    })

    assert values == {1: "class_a", 2: "class_b", 3: unknown_road, 4: unknown_track}


async def test_a_tag_with_the_value_is_true_and_an_absent_tag_is_false(road_graph_session):
    values = await _way_values(road_graph_session, material_sql.tag_is_value_sql("tag_a", "yes"),
                               {1: {"tag_a": " Yes "}, 2: {"tag_a": "no"}, 3: {}})

    assert values == {1: True, 2: False, 3: False}


async def test_a_cycleway_value_on_any_side_counts(road_graph_session):
    values = await _way_values(road_graph_session, material_sql.cycleway_has_value_sql("value_a", "value_b"), {
        1: {"cycleway:both": " Value_B "},
        # 値の無い道も同じ側（NULLだけの配列との`&&`もfalse）。
        2: {"cycleway": "no", "cycleway:left": "other"},
    })

    assert values == {1: True, 2: False}


# 停止要因の種別は区間の値の表の列名を決めるだけで、どの種別でも式は同じ。
_POI_KIND = "signal"


@pytest.mark.parametrize(("count", "distance_m", "expected"), [
    (3.0, 500.0, 6.0),
    (None, 500.0, None),  # 未計算
])
async def test_a_poi_density_is_per_km_and_missing_until_counted(road_graph_session, count, distance_m, expected):
    value = await _edge_value(road_graph_session, material_sql.poi_density_value_sql(_POI_KIND),
                              distance_m=distance_m, **{f"poi_{_POI_KIND}": count})

    assert value == (None if expected is None else pytest.approx(expected))


# --- カタログに直に書かれた式（domain/material_catalog.py） -----------------------------


@pytest.mark.parametrize(("count", "distance_m", "expected"), [
    (2.0, 250.0, 8.0),
    (None, 250.0, None),
])
async def test_the_intersection_density_is_per_km(road_graph_session, count, distance_m, expected):
    value = await _edge_value(road_graph_session, material_value_sql()["intersection_count_per_km"],
                              distance_m=distance_m, intersection_count=count)

    assert value == (None if expected is None else pytest.approx(expected))


@pytest.mark.parametrize(("count", "distance_m", "years", "expected"), [
    (3.0, 500.0, 2, 3.0),
    (None, 500.0, 2, None),
    (3.0, 500.0, 0, None),  # 収録年の無い取込
])
async def test_the_accident_density_is_per_km_and_per_year_covered(road_graph_session, count, distance_m, years,
                                                                    expected):
    value = await _edge_value(road_graph_session, material_value_sql()[ACCIDENT_COUNT_PER_KM_YEAR],
                              distance_m=distance_m, accident_years=years, accident_count=count)

    assert value == (None if expected is None else pytest.approx(expected))


async def test_a_road_is_a_cycleway_by_its_own_kind(road_graph_session):
    values = await _way_values(road_graph_session, material_value_sql()["highway_is_cycleway"],
                               {1: {"highway": "cycleway"}, 2: {"highway": "residential", "cycleway": "track"}})

    assert values == {1: True, 2: False}


async def test_a_shared_pedestrian_path_is_a_footway_or_path_that_lets_bicycles_in(road_graph_session):
    values = await _way_values(road_graph_session, material_value_sql()["shared_pedestrian_path"], {
        1: {"highway": "path", "bicycle": " Designated "},
        2: {"highway": "footway", "bicycle": "no"},
        3: {"highway": "path"},
        4: {"highway": "residential", "bicycle": "yes"},
    })

    assert values == {1: True, 2: False, 3: False, 4: False}


# --- タイルへの載せ方（domain/material_catalog.py: tile_column_sql） ---------------------------


_DENSITY = {"dtype": "numeric", "value_sql": "em.accident_count / (re.distance_m / 1000.0)",
            "tile_encoding": TileEncoding(round_digits=1, omit_zero=True)}
_HAS_ANY = {"dtype": "boolean", "value_sql": "em.accident_count > 0"}


@pytest.mark.parametrize(("fields", "missing", "count", "expected"), [
    (_DENSITY, "unknown", 5.0, "double precision:1.3"),  # ST_AsMVTはnumericを文字列で載せる。地図は数として読めない
    (_DENSITY, "unknown", 0.1, "double precision:null"),  # 丸めて0になる値はキーごと省く（地図は欠損を0として読む）
    (_HAS_ANY, "definite", 0.0, "boolean:null"),  # 非該当はキーごと省く（地図は欠損を非該当として読む）
], ids=["rounded", "zero", "definite-false"])
async def test_a_value_goes_on_the_tile_in_the_form_the_map_reads(road_graph_session, fields, missing, count, expected):
    material = MaterialSpec(material_id="material_a", label="材料A", description="説明", tile_property="material_a",
                            coverage=CoverageExcluded(reason="試し", missing_semantics=missing), **fields)
    column = tile_column_sql(material)

    value = await _edge_value(road_graph_session, f"pg_typeof({column})::text || ':' || coalesce(({column})::text, 'null')",
                              distance_m=4000.0, accident_count=count)

    assert value == expected


# --- 読み出しの経路（infrastructure/road_graph_repository.py） -----------------------------


async def test_the_value_list_of_a_material_has_each_value_once_in_order_without_missing(road_graph_repository):
    """軸スタジオの値の候補。値の無い道は候補を足さない。"""
    await _ingest_ways({1: {"tracktype": "grade3"}, 2: {"tracktype": "grade1"}, 3: {"tracktype": "grade3"}, 4: {}})

    assert await road_graph_repository.get_distinct_material_values("tracktype") == ["grade1", "grade3"]


async def test_a_sample_within_a_range_takes_every_way_in_it_regardless_of_the_sampling_rate(road_graph_repository):
    """`TABLESAMPLE`は表全体のページから抽選するため、狭い範囲と重ねると標本が数本へ落ちる。
    割合0は、抽選が混ざれば1本も返さない。"""
    await _ingest_ways({1: {}, 2: {}})
    area = BoundingBox(min_latitude=35.68, min_longitude=139.69, max_latitude=35.69, max_longitude=139.71)

    samples = await road_graph_repository.sample_way_material_values(1, 0.0, 10, area)

    assert len(samples) == 2


async def test_every_declared_expression_reads_only_what_each_reading_path_provides(road_graph_repository):
    """読む列が無い式が1つでもあると、その経路の読み出しは材料ぶん丸ごと落ちる。列はPostgreSQLが実行の前に
    解決するので、行が無くても確かめられる。"""
    area = BoundingBox(min_latitude=35.0, min_longitude=139.0, max_latitude=35.01, max_longitude=139.01)

    arrays = await road_graph_repository.get_edge_material_arrays([1], [0], [True], 1)
    assert len(arrays.distance_m) == 1
    assert await road_graph_repository.get_way_material_values(1, 1) is None
    assert await road_graph_repository.sample_way_material_values(1, 100.0, 10, None) == []
    assert await road_graph_repository.sample_way_material_values(1, 100.0, 10, area) == []
    for material_id in material_value_sql():
        assert await road_graph_repository.get_distinct_material_values(material_id) == []
    # 取込範囲の外なので焼かずにNoneを返すが、タイルの列は先に解決される。
    assert await road_graph_repository.get_road_surface_tile_mvt(14, 14552, 6451, area) is None
