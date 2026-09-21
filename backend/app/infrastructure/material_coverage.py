"""材料ごとの欠損割合（カバレッジ）を集計クエリで求める読み取り専用リポジトリ。

`GET /api/admin/material-catalog/coverage`（`api/routers/material_catalog.py`）のデータ源。
材料ごとに元データの置き場所が異なる（`osm_raw_ways`の専用列・`tags` JSONBのキー・
Edge単位の派生テーブルの行有無）ため、「どの母集団の、どの条件が成り立てば欠損か」を
材料ごとの宣言（`MaterialSpec.coverage`）から受け取り、母集団ごとに1回の集計クエリへ
まとめる（Edge/Way単位のPythonループは回さない）。ここは測り方の実装だけを持つ。

母集団は2種類:

- `"way"`: `osm_raw_ways`全行（OSMタグ由来の材料）。欠損判定式は`domain/material_sql.py`の
  共有SQL断片を`road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL`（地図タイル配信）と
  共通で使う——両者ともRoad Graphを構築せず`osm_raw_ways`を直接クエリする経路のため、
  独立に書くと片方だけ変更されるドリフトを招く。
- `"edge"`: `road_edges`全行（Edge単位の派生テーブル由来の材料）。派生テーブル
  （`elevation_attributes`・`edge_attribute_counts`）は`edge_id`が`road_edges`へのFK
  （ON DELETE CASCADE）のため、「派生テーブルの該当行数」をそのまま「値ありEdge数」として
  使え、`road_edges`とのJOINを省ける。

「欠損」はあくまで元データ（タグ・行）の不在を指す。評価パイプラインがその不在をどう扱うか
（不明値として評価対象外にするか、タグ不在=非該当のような確定値とみなすか）は材料ごとに
異なるため、`missing_semantics`として併記する。
"""


from dataclasses import dataclass

from app.domain.material_catalog import (
    EdgeMaterialCoverageSpec,
    WayMaterialCoverageSpec,
    material_coverage_exclusions,
    material_coverage_specs,
)
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text

from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS

# 材料ごとの宣言は`MaterialSpec.coverage`が持つ（材料を1つ増やすとき触るのは1か所）。
# ここは測り方の実装だけを持ち、宣言は持たない。
MATERIAL_COVERAGE_SPECS = material_coverage_specs()
MATERIAL_COVERAGE_EXCLUSIONS = material_coverage_exclusions()
MaterialCoverageSpec = WayMaterialCoverageSpec | EdgeMaterialCoverageSpec


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
        f"count(*) FILTER (WHERE ({spec.in_scope}) AND ({spec.missing_condition})) AS {material_id}"
        for material_id, spec in way_specs.items()
    )
    # AS w: domain/material_sql.pyの共有SQL断片がosm_raw_waysをこのエイリアスで
    # 参照する前提のため（_ROAD_SURFACE_TILE_MVT_SQLと同じエイリアス）。
    sql = (  # noqa: S608 固定の内部辞書のみ使用
        f"SELECT count(*) AS total{', ' + columns if columns else ''} FROM osm_raw_ways AS w"
    )
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
