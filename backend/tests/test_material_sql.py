"""`material_sql.py`の導出SQLを、人が書いた期待値で検証する。

地図タイル配信（`_ROAD_SURFACE_TILE_MVT_SQL`）・材料カバレッジ集計・軸スタジオの値列挙は、
`material_catalog.py`のPython extractorを通らずこのSQL断片だけで材料を導出する。
`tests/test_material_catalog.py`はPython側にしか当たらないため、同じ期待値をSQL側へも当てる。

同じ期待値を両方の実装へ当てているので、片方だけを変えたときはここが落ちる。

実DB（ridecompass_test）へ接続するが、テーブルは作らない——断片は`FROM osm_raw_ways AS w`を
前提にエイリアス`w`だけを参照するため、同じ列を持つCTEをwと名付ければ式そのものを評価できる。
"""

import json
from dataclasses import dataclass, field

import pytest
from sqlalchemy import ARRAY, Text, bindparam, text

from app.domain.graph import DirectedEdge
from app.domain.material_catalog import (
    EXTRACTABLE_MATERIAL_IDS,
    MATERIAL_CATALOG,
    MaterialExtractionContext,
    material_value_sql,
)
from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS
from app.domain.material_sql import (
    BICYCLE_NORMALIZED_SQL,
    BRIDGE_NORMALIZED_SQL,
    CYCLEWAY_TAGS_ARRAY_SQL,
    HIGHWAY_SQL,
    LANES_COUNT_CASE_SQL,
    LIT_NORMALIZED_SQL,
    MAXSPEED_KMH_CASE_SQL,
    MOTOR_VEHICLE_NORMALIZED_SQL,
    SMOOTHNESS_NORMALIZED_SQL,
    SURFACE_GOOD_CASE_SQL,
    SURFACE_NORMALIZED_SQL,
    TUNNEL_NORMALIZED_SQL,
)

# 材料id → タイルSQLが焼いているのと同じ式。式をここへ書き写さず`material_sql.py`の
# 断片から組み立てる（写した側だけが古くなるのを防ぐ）。
_SQL_BY_MATERIAL: dict[str, str] = {
    "surface_good": SURFACE_GOOD_CASE_SQL,
    "surface": SURFACE_NORMALIZED_SQL,
    "highway": HIGHWAY_SQL,
    "smoothness": SMOOTHNESS_NORMALIZED_SQL,
    "tracktype": "w.tags->>'tracktype'",
    "has_tunnel": f"CASE WHEN {TUNNEL_NORMALIZED_SQL} = 'yes' THEN true END",
    "bridge": f"CASE WHEN {BRIDGE_NORMALIZED_SQL} = 'yes' THEN true END",
    "maxspeed_kmh": MAXSPEED_KMH_CASE_SQL,
    "lanes_count": LANES_COUNT_CASE_SQL,
    "motor_vehicle_no": f"CASE WHEN {MOTOR_VEHICLE_NORMALIZED_SQL} = 'no' THEN true END",
    "lit": f"CASE WHEN {LIT_NORMALIZED_SQL} = 'yes' THEN true END",
    "highway_is_cycleway": f"CASE WHEN {HIGHWAY_SQL} = 'cycleway' THEN true END",
    "cycleway_has_track": f"CASE WHEN 'track' = ANY({CYCLEWAY_TAGS_ARRAY_SQL}) THEN true END",
    "cycleway_has_lane": f"CASE WHEN 'lane' = ANY({CYCLEWAY_TAGS_ARRAY_SQL}) THEN true END",
    "cycleway_has_shared": (
        f"CASE WHEN {CYCLEWAY_TAGS_ARRAY_SQL} && ARRAY['share_busway', 'shared_lane'] THEN true END"
    ),
    "shared_pedestrian_path": (
        f"CASE WHEN {HIGHWAY_SQL} IN ('footway', 'path') "
        f"AND {BICYCLE_NORMALIZED_SQL} IN ('yes', 'designated') THEN true END"
    ),
}

# 真偽の材料について、SQLとPythonは「該当しない」の表し方が違う。タイルSQLは
# `CASE WHEN 条件 THEN true END`で、**該当しない**と**判定できない**をどちらもNULLへ畳む
# （フィーチャーからキーを省いてタイルを軽くするための符号化）。Pythonのextractorは
# way_tagsがあればFalse、無ければNoneを返し、この2つを区別する。
#
# したがってタイルの式について言えるのは「trueを返すのはPythonがTrueのときだけ」までで、
# ここはそこまでを固定する。**材料の値を求める式（`MATERIAL_VALUE_SQL`）は別物**で、
# そちらは`COALESCE(..., false)`で閉じextractorと同じ2値を返す。
# 例外は`surface_good`だけで、タイルの式も`CASE WHEN 良 THEN true WHEN 悪 THEN false END`。
# 「路面タグ不明」を「路面が悪い」と混同しないという要求が、タイルを軽くする符号化より
# 優先された唯一の材料である。
_SQL_EXPRESSES_FALSE = frozenset({"surface_good"})

_BOOLEAN_MATERIALS = frozenset(
    material_id
    for material_id, spec in MATERIAL_CATALOG.items()
    if spec.dtype == "boolean" and material_id not in _SQL_EXPRESSES_FALSE
)


@dataclass(frozen=True)
class _Case:
    label: str
    expected: dict[str, object]
    highway: str | None = "residential"
    surface: str | None = None
    tags: dict[str, str] = field(default_factory=dict)


# way_tagsが取得できている前提の期待値。挙げていない材料はその入力では判定に関与しない。
_CASES: list[_Case] = [
    _Case(
        label="タグが何も無い住宅道路",
        expected={
            "surface_good": None,
            "surface": None,
            "highway": "residential",
            "smoothness": None,
            "tracktype": None,
            "has_tunnel": False,
            "bridge": False,
            "maxspeed_kmh": None,
            "lanes_count": None,
            "motor_vehicle_no": False,
            "lit": False,
            "highway_is_cycleway": False,
            "cycleway_has_track": False,
            "cycleway_has_lane": False,
            "cycleway_has_shared": False,
            "shared_pedestrian_path": False,
        },
    ),
    _Case(
        label="舗装・街灯あり・制限速度40・2車線",
        highway="primary",
        surface="asphalt",
        tags={"lit": "yes", "maxspeed": "40", "lanes": "2"},
        expected={
            "surface_good": True,
            "surface": "asphalt",
            "highway": "primary",
            "lit": True,
            "maxspeed_kmh": 40,
            "lanes_count": 2,
        },
    ),
    _Case(
        label="未舗装",
        surface="gravel",
        expected={"surface_good": False, "surface": "gravel"},
    ),
    _Case(
        label="未知のsurfaceは悪路ではなく不明",
        surface="unknown_tag",
        expected={"surface_good": None, "surface": "unknown_tag"},
    ),
    _Case(
        label="大文字・前後空白のタグ値は正規化する",
        surface=" Asphalt ",
        tags={"smoothness": " Good "},
        expected={"surface_good": True, "surface": "asphalt", "smoothness": "good"},
    ),
    _Case(
        label="トンネルと橋",
        tags={"tunnel": "yes", "bridge": "yes"},
        expected={"has_tunnel": True, "bridge": True},
    ),
    _Case(
        label="自動車進入禁止",
        tags={"motor_vehicle": "no"},
        expected={"motor_vehicle_no": True},
    ),
    _Case(
        label="0や非数値の制限速度・車線数は不明として扱う",
        tags={"maxspeed": "0", "lanes": "walk"},
        expected={"maxspeed_kmh": None, "lanes_count": None},
    ),
    _Case(
        label="自転車道",
        highway="cycleway",
        expected={"highway_is_cycleway": True, "cycleway_has_track": False},
    ),
    _Case(
        label="片側だけのcycleway_left_track",
        tags={"cycleway:left": "track"},
        expected={
            "cycleway_has_track": True,
            "cycleway_has_lane": False,
            "cycleway_has_shared": False,
        },
    ),
    _Case(
        label="cycleway_lane",
        tags={"cycleway": "lane"},
        expected={"cycleway_has_lane": True, "cycleway_has_track": False},
    ),
    _Case(
        label="cycleway_both_shared_lane",
        tags={"cycleway:both": "shared_lane"},
        expected={"cycleway_has_shared": True, "cycleway_has_lane": False},
    ),
    _Case(
        label="cycleway_share_busway",
        tags={"cycleway": "share_busway"},
        expected={"cycleway_has_shared": True},
    ),
    _Case(
        label="河川敷の歩道兼サイクリングロード",
        highway="footway",
        tags={"bicycle": "designated"},
        expected={"shared_pedestrian_path": True},
    ),
    _Case(
        label="自転車通行不可の歩道",
        highway="footway",
        tags={"bicycle": "no"},
        expected={"shared_pedestrian_path": False},
    ),
    _Case(
        label="bicycle_designatedでもfootway_path以外は該当しない",
        highway="residential",
        tags={"bicycle": "designated"},
        expected={"shared_pedestrian_path": False},
    ),
    _Case(
        label="tracktypeは正規化せず生値を返す",
        highway="track",
        tags={"tracktype": "grade3"},
        expected={"tracktype": "grade3"},
    ),
]

_SELECT_SQL = text(
    "WITH w AS (SELECT CAST(:tags AS jsonb) AS tags, CAST(:surface AS text) AS surface, "
    "CAST(:highway AS text) AS highway) SELECT "
    + ", ".join(f"({expr}) AS m_{name}" for name, expr in _SQL_BY_MATERIAL.items())
    + " FROM w"
).bindparams(
    bindparam("good_tags", value=sorted(GOOD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
    bindparam("bad_tags", value=sorted(BAD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
)


def _expected_sql_value(material_id: str, expected: object) -> object:
    """材料の期待値を、タイルSQLの符号化（trueかNULL）へ写す。"""
    if material_id in _BOOLEAN_MATERIALS:
        return True if expected is True else None
    return expected


def _python_value(case: _Case, material_id: str) -> object:
    spec = MATERIAL_CATALOG[material_id]
    edge = DirectedEdge(
        edge_id="e1",
        from_node_id="n1",
        to_node_id="n2",
        geometry=[[35.0, 139.0], [35.0, 139.001]],
        distance_m=100.0,
        highway=case.highway,
    )
    ctx = MaterialExtractionContext(
        edge_id=edge.edge_id,
        highway=edge.highway,
        way_tags=case.tags,
        distance_km=edge.distance_m / 1000,
        elevation_attributes={},
        surface_attributes={edge.edge_id: case.surface},
        designated_edge_ids=set(),
        metrics={},
        accident_years_covered=1,
    )
    return spec.extractor(ctx)


# SQLを評価するこのテストだけが実DBを要る（Python側の期待値テストは同じ期待値を使うが
# DBに触れない）。road_graph_sessionはファイル単位でエンジン・イベントループを共有する
# 設計のため、loop_scopeをそれに合わせる（docs/testing.md参照）。
@pytest.mark.postgis
@pytest.mark.xdist_group(name="postgis")
@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("case", _CASES, ids=lambda c: c.label)
async def test_sql_derivation_matches_written_expectations(road_graph_session, case: _Case):
    row = (
        await road_graph_session.execute(
            _SELECT_SQL,
            {"tags": json.dumps(case.tags), "surface": case.surface, "highway": case.highway},
        )
    ).one()
    for material_id, expected in case.expected.items():
        actual = getattr(row, f"m_{material_id}")
        want = _expected_sql_value(material_id, expected)
        assert actual == want, f"SQL側の{material_id}: {actual!r} ≠ 期待{want!r}（材料としては{expected!r}）"


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c.label)
def test_python_extractor_matches_the_same_expectations(case: _Case):
    for material_id, expected in case.expected.items():
        actual = _python_value(case, material_id)
        assert actual == expected, f"Python側の{material_id}: {actual!r} ≠ 期待{expected!r}"


def test_every_sql_derived_material_is_in_the_catalog():
    """SQLだけが知っている材料を作らない（カタログが材料の登録先の唯一）。"""
    assert set(_SQL_BY_MATERIAL) <= set(MATERIAL_CATALOG)


def test_value_sql_and_extractor_cover_the_same_materials():
    """`value_sql`とextractorは同じ材料集合を覆う。

    どちらも`MaterialSpec`のフィールドだが、片方だけ書いても構文は通る。SQLで求められない
    材料（リクエスト時に決まる風、評価へ配線していないDEFER材料）はextractorも持たないため、
    両者は常に一致する。
    """
    assert set(material_value_sql()) == set(EXTRACTABLE_MATERIAL_IDS)
