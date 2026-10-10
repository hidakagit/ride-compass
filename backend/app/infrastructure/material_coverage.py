"""材料ごとの欠損割合（カバレッジ）を集計クエリで求める読み取り専用リポジトリ。

`GET /api/admin/material-catalog/coverage`（`api/routers/material_catalog.py`）のデータ源。
材料ごとに元データの置き場所が異なる（道の生データのタグ・区間の材料の列）ため、「どの母集団の、どの条件が成り立てば欠損か」を
材料ごとの宣言（`MaterialSpec.coverage`）から受け取り、集計クエリで数える（Edge/Way単位の
Pythonループは回さない）。ここは測り方の実装だけを持つ。

母集団は2種類:

- `"way"`: 道の生データ全行（`WAYS_SOURCE_SQL`、OSMタグ由来の材料）。全材料が同じ行の
  タグを見るため、材料ごとの`count(*) FILTER`を並べた1回の走査にまとめる。欠損判定式は
  `domain/material_sql.py`の共有SQL断片を`road_graph_repository.py: ROAD_SURFACE_TILE_MVT_SQL`
  （地図タイル配信）と共通で使う——両者ともRoad Graphを構築せずDBを直接引く経路のため、
  独立に書くと片方だけ変更されるドリフトを招く。
- `"edge"`: `road_edges`全行（Edge単位の材料）。区間の値（別名`em`）の表を区間へ結ばずに走査して値のある区間を
  数え、総数は`road_edges`の件数とする。判定式が読む表は宣言から引き（`road_graph_repository.py: edge_material_table`）、
  way側と同じく材料ごとの`count(*) FILTER`を並べて表ごとに1回の走査にまとめる。

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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.road_graph_repository import edge_material_table
from app.infrastructure.source_models import WAYS_SOURCE_SQL

# 材料ごとの宣言は`MaterialSpec.coverage`が持つ（材料を1つ増やすとき触るのは1か所）。
# ここは測り方の実装だけを持ち、宣言は持たない。
MATERIAL_COVERAGE_SPECS = material_coverage_specs()
MATERIAL_COVERAGE_EXCLUSIONS = material_coverage_exclusions()


@dataclass(frozen=True)
class MaterialCoverageCounts:
    """集計クエリの生の結果。`missing_by_material`は`MATERIAL_COVERAGE_SPECS`の全キーを持つ。"""

    way_total: int
    edge_total: int
    missing_by_material: dict[str, int]


_WAY_SPECS = {
    material_id: spec
    for material_id, spec in MATERIAL_COVERAGE_SPECS.items()
    if isinstance(spec, WayMaterialCoverageSpec)
}
_EDGE_SPECS = {
    material_id: spec
    for material_id, spec in MATERIAL_COVERAGE_SPECS.items()
    if isinstance(spec, EdgeMaterialCoverageSpec)
}


def _way_coverage_sql():
    """way母集団の全材料を1回の走査で数えるSELECT文（`count(*) FILTER`列を材料ごとに並べる）。
    列別名は材料id（内部定数のみ、外部入力を連結しない）。"""
    columns = ", ".join(
        f"count(*) FILTER (WHERE {spec.missing_condition}) AS {material_id}"
        for material_id, spec in _WAY_SPECS.items()
    )
    # 元データの引き方は`domain/material_sql.py`が持つ。ここで書き写すと、生データの
    # 置き場が変わったときにこの1本だけが古いテーブルを指したまま残る。
    sql = (  # noqa: S608 固定の内部辞書のみ使用
        f"SELECT count(*) AS total{', ' + columns if columns else ''} FROM {WAYS_SOURCE_SQL} AS w"
    )
    return text(sql)


def _edge_coverage_sql():
    """edge母集団の全材料の「値ありEdge数」を数えるSELECT文。区間の値の表ごとに1回の走査。列別名は材料id。"""
    columns_by_table: dict[str, list[str]] = {}
    for material_id, spec in _EDGE_SPECS.items():
        columns_by_table.setdefault(edge_material_table(spec.present_condition), []).append(
            f"count(*) FILTER (WHERE {spec.present_condition}) AS {material_id}")
    # 区間へ結ばずに値の表だけを走査する（区間の全件へ結ぶと、値の表の全件のハッシュがwork_memから溢れる）。
    # 判定式が`re.`（区間の形）を読むようになったら、この形では組めないので区間へ結ぶ形に戻す。
    scans = [f"(SELECT {', '.join(columns)} FROM {table} em) t_{table}"
             for table, columns in columns_by_table.items()]
    sql = (  # noqa: S608 固定の内部辞書のみ使用
        "SELECT (SELECT count(*) FROM road_edges) AS total"
        + (", * FROM " + " CROSS JOIN ".join(scans) if scans else "")
    )
    return text(sql)


class MaterialCoverageQuery:
    """読み取り専用でcommit対象の書き込みは無い。全表走査を伴うため管理API専用
    （`api/dependencies.py: get_material_coverage_service`が長いcommand_timeoutのセッションを渡す）。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_material_coverage_counts(self) -> MaterialCoverageCounts:
        missing_by_material: dict[str, int] = {}

        way_row = (await self._session.execute(_way_coverage_sql())).mappings().one()
        way_total = int(way_row["total"])
        for material_id in _WAY_SPECS:
            missing_by_material[material_id] = int(way_row[material_id])

        edge_row = (await self._session.execute(_edge_coverage_sql())).mappings().one()
        edge_total = int(edge_row["total"])
        for material_id in _EDGE_SPECS:
            missing_by_material[material_id] = edge_total - int(edge_row[material_id])

        return MaterialCoverageCounts(
            way_total=way_total, edge_total=edge_total, missing_by_material=missing_by_material
        )
