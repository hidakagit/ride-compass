"""材料ごとの欠損割合（カバレッジ）を集計クエリで求める読み取り専用リポジトリ。

`GET /api/admin/material-catalog/coverage`（`api/routers/material_catalog.py`）のデータ源。
材料ごとに元データの置き場所が異なる（道の生データのタグ・区間の材料の列）ため、「どの母集団の、どの条件が成り立てば欠損か」を
材料ごとの宣言（`MaterialSpec.coverage`）から受け取り、集計クエリで数える（Edge/Way単位の
Pythonループは回さない）。ここは測り方の実装だけを持つ。

母集団は2種類:

- `"way"`: 道の生データ全行（`WAYS_SOURCE_SQL`、OSMタグ由来の材料）。全材料が同じ行の
  タグを見るため、材料ごとの`count(*) FILTER`を並べた1回の走査にまとめる。欠損判定式は
  `domain/material_sql.py`の共有SQL断片を`road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL`
  （地図タイル配信）と共通で使う——両者ともRoad Graphを構築せずDBを直接引く経路のため、
  独立に書くと片方だけ変更されるドリフトを招く。
- `"edge"`: `road_edges`全行（Edge単位の材料）。値は`edge_materials`の列に並び、その
  `(osm_way_id, segment_index)`は`road_edges`へのFK（ON DELETE CASCADE）のため、「値が
  埋まっている行数」をそのまま「値ありEdge数」として使え、`road_edges`とのJOINを省ける。way側と同じく
  材料ごとの`count(*) FILTER`を並べた1回の走査にまとめる。

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

from app.domain.material_sql import WAYS_SOURCE_SQL
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
    # 元データの引き方は`domain/material_sql.py`が持つ。ここで書き写すと、生データの
    # 置き場が変わったときにこの1本だけが古いテーブルを指したまま残る。
    sql = (  # noqa: S608 固定の内部辞書のみ使用
        f"SELECT count(*) AS total{', ' + columns if columns else ''} FROM {WAYS_SOURCE_SQL} AS w"
    )
    statement = text(sql)
    if ":good_tags" in sql:
        statement = statement.bindparams(
            bindparam("good_tags", value=sorted(GOOD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
            bindparam("bad_tags", value=sorted(BAD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
        )
    return statement


def build_edge_coverage_sql(specs: dict[str, MaterialCoverageSpec] = MATERIAL_COVERAGE_SPECS):
    """edge母集団の全材料の「値ありEdge数」を1回の走査で数えるSELECT文。列別名は材料id。"""
    columns = ", ".join(
        f"count(*) FILTER (WHERE {spec.present_condition}) AS {material_id}"
        for material_id, spec in specs.items()
        if isinstance(spec, EdgeMaterialCoverageSpec)
    )
    sql = (  # noqa: S608 固定の内部辞書のみ使用
        f"SELECT (SELECT count(*) FROM road_edges) AS total{', ' + columns if columns else ''}"
        " FROM edge_materials AS em"
    )
    return text(sql)


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

        edge_row = (await self._session.execute(build_edge_coverage_sql())).mappings().one()
        edge_total = int(edge_row["total"])
        for material_id, spec in MATERIAL_COVERAGE_SPECS.items():
            if isinstance(spec, EdgeMaterialCoverageSpec):
                missing_by_material[material_id] = max(edge_total - int(edge_row[material_id]), 0)

        return MaterialCoverageCounts(
            way_total=way_total, edge_total=edge_total, missing_by_material=missing_by_material
        )
