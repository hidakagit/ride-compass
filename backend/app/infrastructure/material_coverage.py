"""材料ごとの欠損割合（カバレッジ）を集計クエリで求める読み取り専用リポジトリ。

`GET /api/admin/material-catalog/coverage`（`api/routers/material_catalog.py`）のデータ源。
材料ごとに元データの置き場所が異なる（`osm_raw_ways`の専用列・`tags` JSONBのキー・
Edge単位の派生テーブルの行有無）ため、材料id→「どの母集団の、どの条件が成り立てば欠損か」を
宣言テーブル（`MATERIAL_COVERAGE_SPECS`）として持ち、母集団ごとに1回の集計クエリへまとめる
（Edge/Way単位のPythonループは回さない）。

母集団は2種類:

- `"way"`: `osm_raw_ways`全行（OSMタグ由来の材料）。欠損判定式は`infrastructure/
  osm_way_tag_sql.py`の共有SQL断片を`road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL`
  （地図タイル配信）と共通で使う——両者ともRoad Graphを構築せず`osm_raw_ways`を直接
  クエリする経路のため、独立に書くと片方だけ変更されるドリフトを招く。
- `"edge"`: `road_edges`全行（Edge単位の派生テーブル由来の材料）。派生テーブル
  （`elevation_attributes`・`edge_attribute_counts`）は`edge_id`が`road_edges`へのFK
  （ON DELETE CASCADE）のため、「派生テーブルの該当行数」をそのまま「値ありEdge数」として
  使え、`road_edges`とのJOINを省ける。

「欠損」はあくまで元データ（タグ・行）の不在を指す。評価パイプラインがその不在をどう扱うか
（不明値として評価対象外にするか、タグ不在=非該当のような確定値とみなすか）は材料ごとに
異なるため、`missing_semantics`として併記する（`MATERIAL_CATALOG`の`bool_default`からは
導出しない——`bool_default="nan"`でもextractorがタグ不在を確定値として扱う材料があり、
実際の扱いはextractorの実装で決まるため）。

材料カタログ（`domain/material_catalog.py: MATERIAL_CATALOG`）の全材料は、本テーブルか
`MATERIAL_COVERAGE_EXCLUSIONS`（理由付きの対象外一覧）のどちらか一方に必ず載せる
（`tests/test_material_coverage.py`が網羅性を検証する）。
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text

from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS
from app.infrastructure.osm_way_tag_sql import (
    BICYCLE_NORMALIZED_SQL,
    BRIDGE_NORMALIZED_SQL,
    CYCLEWAY_TAG_NAMES,
    HIGHWAY_SQL,
    LANES_COUNT_CASE_SQL,
    LIT_NORMALIZED_SQL,
    MAXSPEED_KMH_CASE_SQL,
    MOTOR_VEHICLE_NORMALIZED_SQL,
    SMOOTHNESS_NORMALIZED_SQL,
    SURFACE_GOOD_CASE_SQL,
    SURFACE_NORMALIZED_SQL,
    TUNNEL_NORMALIZED_SQL,
    normalized_tag_sql,
)

Population = Literal["way", "edge"]
# "unknown": 欠損は不明値（NaN/None）として扱われ、その材料を使う軸は評価対象外になる。
# "definite": 欠損は確定値（タグ不在=非該当等）として扱われ、軸は通常どおり評価される。
MissingSemantics = Literal["unknown", "definite"]


@dataclass(frozen=True)
class WayMaterialCoverageSpec:
    """`osm_raw_ways`全行を母集団とする材料。`missing_condition`は`osm_raw_ways`の列・
    JSONB参照のみで構成したSQL真偽式（trueなら欠損）で、外部入力を連結しない。"""

    missing_condition: str
    source: str
    missing_semantics: MissingSemantics
    population: Population = "way"


@dataclass(frozen=True)
class EdgeMaterialCoverageSpec:
    """`road_edges`全行を母集団とする材料。`present_count_sql`は「値を持つEdge数」を1行1列で
    返すSELECT文（派生テーブル側だけを数える。FK CASCADEにより行は必ず既存Edgeに対応する）。"""

    present_count_sql: str
    source: str
    missing_semantics: MissingSemantics
    population: Population = "edge"


MaterialCoverageSpec = WayMaterialCoverageSpec | EdgeMaterialCoverageSpec


_CYCLEWAY_TAGS_ALL_ABSENT = " AND ".join(f"tags->>'{tag}' IS NULL" for tag in CYCLEWAY_TAG_NAMES)
_CYCLEWAY_SOURCE = "osm_raw_ways.tags の cycleway / cycleway:left / cycleway:right / cycleway:both（いずれも無い場合に欠損）"
_EDGE_ATTRIBUTE_COUNTS_PRESENT_SQL = "SELECT count(*) FROM edge_attribute_counts"
_EDGE_ATTRIBUTE_COUNTS_SOURCE = "edge_attribute_counts（Edge単位の事前集計行）の有無"


MATERIAL_COVERAGE_SPECS: dict[str, MaterialCoverageSpec] = {
    "highway": WayMaterialCoverageSpec(
        missing_condition=f"{HIGHWAY_SQL} IS NULL",
        source="osm_raw_ways.highway",
        missing_semantics="unknown",
    ),
    "surface": WayMaterialCoverageSpec(
        missing_condition=f"{SURFACE_NORMALIZED_SQL} IS NULL",
        source="osm_raw_ways.surface",
        missing_semantics="unknown",
    ),
    "surface_good": WayMaterialCoverageSpec(
        missing_condition=f"({SURFACE_GOOD_CASE_SQL}) IS NULL",
        source="osm_raw_ways.surface（良否いずれの分類にも該当しない値も欠損に含む）",
        missing_semantics="unknown",
    ),
    "smoothness": WayMaterialCoverageSpec(
        missing_condition=f"{SMOOTHNESS_NORMALIZED_SQL} IS NULL",
        source="osm_raw_ways.tags->>'smoothness'",
        missing_semantics="unknown",
    ),
    "tracktype": WayMaterialCoverageSpec(
        missing_condition=f"{normalized_tag_sql('tracktype')} IS NULL",
        source="osm_raw_ways.tags->>'tracktype'",
        missing_semantics="unknown",
    ),
    "maxspeed_kmh": WayMaterialCoverageSpec(
        missing_condition=f"({MAXSPEED_KMH_CASE_SQL}) IS NULL",
        source="osm_raw_ways.tags->>'maxspeed'（数値として解釈できない値も欠損に含む）",
        missing_semantics="unknown",
    ),
    "lanes_count": WayMaterialCoverageSpec(
        missing_condition=f"({LANES_COUNT_CASE_SQL}) IS NULL",
        source="osm_raw_ways.tags->>'lanes'（数値として解釈できない値も欠損に含む）",
        missing_semantics="unknown",
    ),
    "lit": WayMaterialCoverageSpec(
        missing_condition=f"{LIT_NORMALIZED_SQL} IS NULL",
        source="osm_raw_ways.tags->>'lit'（タグ不在は街灯なし扱い）",
        missing_semantics="definite",
    ),
    "has_tunnel": WayMaterialCoverageSpec(
        missing_condition=f"{TUNNEL_NORMALIZED_SQL} IS NULL",
        source="osm_raw_ways.tags->>'tunnel'（タグ不在は非該当扱い）",
        missing_semantics="definite",
    ),
    "bridge": WayMaterialCoverageSpec(
        missing_condition=f"{BRIDGE_NORMALIZED_SQL} IS NULL",
        source="osm_raw_ways.tags->>'bridge'（タグ不在は非該当扱い）",
        missing_semantics="definite",
    ),
    "motor_vehicle_no": WayMaterialCoverageSpec(
        missing_condition=f"{MOTOR_VEHICLE_NORMALIZED_SQL} IS NULL",
        source="osm_raw_ways.tags->>'motor_vehicle'（タグ不在は通行可扱い）",
        missing_semantics="definite",
    ),
    "highway_is_cycleway": WayMaterialCoverageSpec(
        missing_condition=f"{HIGHWAY_SQL} IS NULL",
        source="osm_raw_ways.highway",
        missing_semantics="definite",
    ),
    "cycleway_has_track": WayMaterialCoverageSpec(
        missing_condition=_CYCLEWAY_TAGS_ALL_ABSENT,
        source=_CYCLEWAY_SOURCE,
        missing_semantics="definite",
    ),
    "cycleway_has_lane": WayMaterialCoverageSpec(
        missing_condition=_CYCLEWAY_TAGS_ALL_ABSENT,
        source=_CYCLEWAY_SOURCE,
        missing_semantics="definite",
    ),
    "cycleway_has_shared": WayMaterialCoverageSpec(
        missing_condition=_CYCLEWAY_TAGS_ALL_ABSENT,
        source=_CYCLEWAY_SOURCE,
        missing_semantics="definite",
    ),
    "shared_pedestrian_path": WayMaterialCoverageSpec(
        missing_condition=f"{BICYCLE_NORMALIZED_SQL} IS NULL",
        source="osm_raw_ways.tags->>'bicycle'（highway=footway/pathとの組み合わせで判定、タグ不在は非該当扱い）",
        missing_semantics="definite",
    ),
    "gradient_percent": EdgeMaterialCoverageSpec(
        present_count_sql="SELECT count(*) FROM elevation_attributes WHERE average_grade IS NOT NULL",
        source="elevation_attributes.average_grade（precompute_elevation_attributesの計算済み行）の有無",
        missing_semantics="unknown",
    ),
    "stop_count_per_km": EdgeMaterialCoverageSpec(
        present_count_sql=_EDGE_ATTRIBUTE_COUNTS_PRESENT_SQL,
        source=_EDGE_ATTRIBUTE_COUNTS_SOURCE,
        missing_semantics="unknown",
    ),
    "intersection_count_per_km": EdgeMaterialCoverageSpec(
        present_count_sql=_EDGE_ATTRIBUTE_COUNTS_PRESENT_SQL,
        source=_EDGE_ATTRIBUTE_COUNTS_SOURCE,
        missing_semantics="unknown",
    ),
    "accident_count_per_km_year": EdgeMaterialCoverageSpec(
        present_count_sql=_EDGE_ATTRIBUTE_COUNTS_PRESENT_SQL,
        source=_EDGE_ATTRIBUTE_COUNTS_SOURCE,
        missing_semantics="unknown",
    ),
    "trees_percent": WayMaterialCoverageSpec(
        missing_condition="NOT EXISTS (SELECT 1 FROM way_landcover lc WHERE lc.osm_way_id = w.osm_way_id)",
        source="way_landcover（precompute_way_landcoverの計算済み行）の有無",
        missing_semantics="unknown",
    ),
    "built_percent": WayMaterialCoverageSpec(
        missing_condition="NOT EXISTS (SELECT 1 FROM way_landcover lc WHERE lc.osm_way_id = w.osm_way_id)",
        source="way_landcover（precompute_way_landcoverの計算済み行）の有無",
        missing_semantics="unknown",
    ),
}


# 欠損割合の集計対象外とする材料と、その理由（管理画面にそのまま表示する）。
MATERIAL_COVERAGE_EXCLUSIONS: dict[str, str] = {
    "wind_drag_ratio": "出発時刻の気象予報・想定速度から都度計算する動的材料で、DBに静的な値を持たない",
    "oneway": "osm_raw_ways.directionはNOT NULL列で、タグ不在は双方向(both)に解決済み（欠損の概念が無い）",
    "designation": "designation_attributes行の有無がそのまま該当/非該当の確定値（欠損の概念が無い）",
    "is_emergency_transport": "designation_attributes行の有無がそのまま該当/非該当の確定値（欠損の概念が無い）",
    "is_critical_logistics": "designation_attributes行の有無がそのまま該当/非該当の確定値（欠損の概念が無い）",
    "is_designated": "designation_attributes行の有無がそのまま該当/非該当の確定値（欠損の概念が無い）",
}


@dataclass(frozen=True)
class MaterialCoverageCounts:
    """集計クエリの生の結果。`missing_by_material`は`MATERIAL_COVERAGE_SPECS`の全キーを持つ。"""

    way_total: int
    edge_total: int
    missing_by_material: dict[str, int]


def build_way_coverage_sql(specs: dict[str, MaterialCoverageSpec] = MATERIAL_COVERAGE_SPECS):
    """way母集団の全材料を1回の走査で数えるSELECT文（`count(*) FILTER`列を材料ごとに並べる）。
    列別名は材料id（内部定数のみ、外部入力を連結しない）。"""
    way_specs = {material_id: spec for material_id, spec in specs.items() if isinstance(spec, WayMaterialCoverageSpec)}
    columns = ", ".join(
        f"count(*) FILTER (WHERE {spec.missing_condition}) AS {material_id}" for material_id, spec in way_specs.items()
    )
    # AS w: infrastructure/osm_way_tag_sql.pyの共有SQL断片がosm_raw_waysをこのエイリアスで
    # 参照する前提のため（_ROAD_SURFACE_TILE_MVT_SQLと同じエイリアス）。
    sql = f"SELECT count(*) AS total{', ' + columns if columns else ''} FROM osm_raw_ways AS w"  # noqa: S608 固定の内部辞書のみ使用
    statement = text(sql)
    if ":good_tags" in sql:
        statement = statement.bindparams(
            bindparam("good_tags", value=sorted(GOOD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
            bindparam("bad_tags", value=sorted(BAD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
        )
    return statement


class MaterialCoverageQuery:
    """読み取り専用でcommit対象の書き込みは無い。全表走査を伴うため管理API専用
    （`api/dependencies.py: get_material_coverage_service`が長いcommand_timeoutのセッションを渡す）。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_material_coverage_counts(self) -> MaterialCoverageCounts:
        missing_by_material: dict[str, int] = {}

        way_row = (await self._session.execute(build_way_coverage_sql())).mappings().one()
        way_total = int(way_row["total"])
        for material_id, spec in MATERIAL_COVERAGE_SPECS.items():
            if isinstance(spec, WayMaterialCoverageSpec):
                missing_by_material[material_id] = int(way_row[material_id])

        edge_total = int((await self._session.execute(text("SELECT count(*) FROM road_edges"))).scalar_one())
        present_count_by_sql: dict[str, int] = {}
        for material_id, spec in MATERIAL_COVERAGE_SPECS.items():
            if not isinstance(spec, EdgeMaterialCoverageSpec):
                continue
            if spec.present_count_sql not in present_count_by_sql:
                present = int((await self._session.execute(text(spec.present_count_sql))).scalar_one())
                present_count_by_sql[spec.present_count_sql] = present
            missing_by_material[material_id] = max(edge_total - present_count_by_sql[spec.present_count_sql], 0)

        return MaterialCoverageCounts(
            way_total=way_total, edge_total=edge_total, missing_by_material=missing_by_material
        )
