"""edge_landcoverの事前集計バッチ。

`precompute_way_landcover.py`と同じリング・同じ割合の算出（`_landcover.py`を共有）を、
way丸ごとではなく**区間（`road_edges`）**に対して行う。母集団が違うだけで、値の意味は同じ。

`road_edges`はforward/backwardを別行で持つため、**向きに依らない区間の同定子**
（way＋両端ノードの小さい方・大きい方）ごとに1回だけ読む。路面タイルが代表として残す行は
`edge_id`昇順で決まり、materialが代表の向きにしか無いと値が落ちるため、鍵をedge_idにしない
（`road_graph_repository.py: _TILE_FEATURE_SOURCE_SQL`が`node_lo`/`node_hi`を出しているのと
同じ理由）。

`way_landcover`は置き換えない。`road_edges`は`presplit_road_graph.py`が埋める派生データで、
区間を持たないwayや未splitの範囲には行が作れないため、読み出し側はここに行が無ければway単位の
値へ落とす。

**このバッチをDBホスト（本番VM）上で走らせない**。本番DBはbackendと同じVMに同居しており、
重いバッチはVM全体を巻き込む（docs/disaster-recovery.md「既知のリスク」）。開発機から
`--database-url`で本番DBへ接続して実行する（`precompute_way_landcover.py`の本番実行と同じ
方法、docs/tasks/T624.md段階3）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.precompute_edge_landcover --raster <path>
    --dry-runで対象件数のログのみ（DB書き込み・ラスタ読み込みなし）
"""

import functools
import logging
import sys

import shapely
from shapely.geometry import LineString
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch._landcover import (
    LandcoverPlan,
    landcover_batch_main,
    run_landcover_batch,
    run_with_configured_rasters,
)
from app.domain.derived_data_versions import (
    LANDCOVER_ALGORITHM_VERSION,
    LANDCOVER_DEFAULT_BUFFER_M,
    LANDCOVER_DEFAULT_INNER_M,
    landcover_algorithm_version,
)
from app.domain.landcover import EdgeLandcover
from app.infrastructure.road_graph_models import EdgeLandcoverRow, RoadEdgeRow

logger = logging.getLogger("ridecompass.precompute_edge_landcover")

CHUNK_SIZE = 5_000
DEFAULT_BUFFER_M = LANDCOVER_DEFAULT_BUFFER_M
DEFAULT_INNER_M = LANDCOVER_DEFAULT_INNER_M
DATA_SOURCE = "esri-io-lulc"

_LATEST_SUCCEEDED_OSM_RUN_ID_SQL = text("SELECT MAX(id) FROM osm_import_runs WHERE status = 'succeeded'")

algorithm_version = landcover_algorithm_version
ALGORITHM_VERSION = LANDCOVER_ALGORITHM_VERSION


def _representative_edges():
    """物理区間ごとに1本だけ残した`road_edges`。残す側は`edge_id`昇順で決定論的に固定する
    （路面タイルの重複排除と同じ鍵・同じ規則、`_TILE_FEATURE_SOURCE_SQL`参照）。"""
    node_lo = func.least(RoadEdgeRow.from_node_id, RoadEdgeRow.to_node_id).label("node_lo")
    node_hi = func.greatest(RoadEdgeRow.from_node_id, RoadEdgeRow.to_node_id).label("node_hi")
    return (
        select(
            RoadEdgeRow.edge_id.label("edge_id"),
            RoadEdgeRow.osm_way_id.label("osm_way_id"),
            node_lo,
            node_hi,
            RoadEdgeRow.geom.label("geom"),
        )
        .where(RoadEdgeRow.osm_way_id.is_not(None))
        .distinct(RoadEdgeRow.osm_way_id, node_lo, node_hi)
        .order_by(RoadEdgeRow.osm_way_id, node_lo, node_hi, RoadEdgeRow.edge_id)
        .subquery()
    )


def _target_edge_ids_stmt(recompute: bool, raster_set: str | None = None, algorithm: str | None = None):
    """対象区間の代表`edge_id`を地理的順序で選ぶselect。`recompute=False`（既定）では
    既に結果を持つ区間をanti-joinで除外する（`precompute_way_landcover.py`と同じ考え方——
    除外するのは「値を持つ行」と「今回と同じラスタ構成・同じアルゴリズムで値なしと確定済み」）。
    """
    rep = _representative_edges()
    stmt = select(rep.c.edge_id)
    if not recompute:
        stmt = stmt.outerjoin(
            EdgeLandcoverRow,
            and_(
                EdgeLandcoverRow.osm_way_id == rep.c.osm_way_id,
                EdgeLandcoverRow.node_lo == rep.c.node_lo,
                EdgeLandcoverRow.node_hi == rep.c.node_hi,
            ),
        ).where(
            or_(
                EdgeLandcoverRow.osm_way_id.is_(None),
                and_(
                    EdgeLandcoverRow.trees_percent.is_(None),
                    or_(
                        EdgeLandcoverRow.source_raster_set.is_distinct_from(raster_set),
                        EdgeLandcoverRow.algorithm_version.is_distinct_from(algorithm),
                    ),
                ),
            )
        )
    else:
        stmt = stmt.select_from(rep)
    return stmt.order_by(rep.c.geom)


async def _fetch_segments(
    session: AsyncSession, edge_ids: list[str]
) -> list[tuple[tuple[int, str, str], LineString]]:
    """代表edge_idから、区間の同定子（way＋両端ノード）とジオメトリを引く。"""
    stmt = select(
        RoadEdgeRow.osm_way_id,
        func.least(RoadEdgeRow.from_node_id, RoadEdgeRow.to_node_id),
        func.greatest(RoadEdgeRow.from_node_id, RoadEdgeRow.to_node_id),
        RoadEdgeRow.geom,
    ).where(RoadEdgeRow.edge_id.in_(edge_ids))
    rows = (await session.execute(stmt)).all()
    if not rows:
        return []
    geometries = shapely.from_wkb([bytes(row[3].data) for row in rows])
    return [((row[0], row[1], row[2]), geom) for row, geom in zip(rows, geometries)]


def _plan(version: str, raster_set: str, recompute: bool) -> LandcoverPlan:
    return LandcoverPlan(
        label="区間",
        logger=logger,
        chunk_size=CHUNK_SIZE,
        empty_warning=(
            "対象区間が0件のため更新をスキップします"
            "（road_edgesが空[presplit_road_graph.py未実行]、または全件計算済みの可能性）"
        ),
        target_stmt=_target_edge_ids_stmt(recompute, raster_set, version),
        fetch=_fetch_segments,
        build=lambda key, percentages, stamp: EdgeLandcover(
            osm_way_id=key[0],
            node_lo=key[1],
            node_hi=key[2],
            percentages=percentages,
            data_source=DATA_SOURCE,
            data_version=stamp.data_version,
            computed_at=stamp.computed_at,
            source_osm_import_run_id=stamp.source_osm_import_run_id,
            algorithm_version=stamp.algorithm_version,
            source_raster_set=stamp.source_raster_set,
        ),
        save=lambda repository, records: repository.save_edge_landcover(records),
    )


# このモジュールが持つのは母集団の違い（`_plan`）だけで、実行・CLI・`refresh_derived.py`
# 向けの口は共有側にある。いずれも`_plan`を渡すだけの束ねのため、関数として書き直さない
# （書き直すと2本のバッチで同じ定型が並び、片方だけ引数が増えても気づけない）。
run = functools.partial(run_landcover_batch, _plan)
run_default = functools.partial(
    run_with_configured_rasters, _plan, buffer_m=DEFAULT_BUFFER_M, inner_m=DEFAULT_INNER_M
)
main = functools.partial(
    landcover_batch_main,
    description="edge_landcover事前集計バッチ",
    recompute_help="既存行の有無に関わらず対象区間全件を再計算する",
    make_plan=_plan,
    buffer_m=DEFAULT_BUFFER_M,
    inner_m=DEFAULT_INNER_M,
)


if __name__ == "__main__":
    sys.exit(main())
