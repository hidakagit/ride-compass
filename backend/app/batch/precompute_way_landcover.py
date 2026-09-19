"""way_landcoverの事前集計バッチ。

道路centerline（`osm_raw_ways.geom`）の周囲100mリング（既定、`--buffer-m`/`--inner-m`で
変更可）内の土地被覆クラス別画素数を、Esri×Impact ObservatoryのGeoTIFF（`--raster`で
指定、複数ファイル可）から`rasterio`で読み取り、`domain/landcover.py: class_percentages`で
割合(%)へ変換して`way_landcover`へUPSERTする。母集団は`osm_raw_ways`全域
（geom・highwayを持つway）で、Road Graph（road_edges）には依存しない
（`precompute_way_attribute_counts.py`と同じ理由）。

ラスタファイルはリポジトリにコミットしない（手動取得、docs/disaster-recovery.md参照）。
複数ファイルを渡した場合、各wayは**リングを完全に含む**最初のファイルで処理する
（`--recompute`無しなら`way_landcover`に未だ行が無いwayだけを対象にする増分実行）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.precompute_way_landcover --raster <path>
    --dry-runで対象件数のログのみ（DB書き込み・ラスタ読み込みなし）
"""

import functools
import logging
import sys

import shapely
from shapely.geometry import LineString
from sqlalchemy import and_, or_, select, text
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
from app.domain.landcover import WayLandcover
from app.infrastructure.road_graph_models import OsmRawWayRow, WayLandcoverRow

logger = logging.getLogger("ridecompass.precompute_way_landcover")

CHUNK_SIZE = 5_000
DEFAULT_BUFFER_M = LANDCOVER_DEFAULT_BUFFER_M
DEFAULT_INNER_M = LANDCOVER_DEFAULT_INNER_M
DATA_SOURCE = "esri-io-lulc"

_LATEST_SUCCEEDED_OSM_RUN_ID_SQL = text("SELECT MAX(id) FROM osm_import_runs WHERE status = 'succeeded'")


# 径ごとに版文字列を変える規則そのものは`domain/derived_data_versions.py`が持つ
# （鮮度台帳もこの規則で現在の版を組み立てる）。
algorithm_version = landcover_algorithm_version


# 現在の既定リング径での版数。--buffer-m/--inner-mでこれと異なる値を指定して実行すると、
# 鮮度台帳はその行を古い版として検知する（径ごとに版文字列が変わるため）。
ALGORITHM_VERSION = LANDCOVER_ALGORITHM_VERSION


def _target_way_ids_stmt(recompute: bool, raster_set: str | None = None, algorithm: str | None = None):
    """対象way（geom・highwayを持つ）のosm_way_idを地理的順序で選ぶselect。`recompute=False`
    （既定）では既に結果を持つwayをanti-joinで除外する増分実行
    （`precompute_elevation_attributes.py`と同じ考え方）。

    除外するのは「値を持つ行があるway」と「今回と同じラスタ構成・同じアルゴリズムで
    値なしと確定済みのway」。値なしの行を持っていても、ラスタ構成かアルゴリズムが
    変われば結果が変わりうるため対象へ戻す（`raster_set_fingerprint`参照）。
    """
    stmt = (
        select(OsmRawWayRow.osm_way_id)
        .where(OsmRawWayRow.geom.is_not(None))
        .where(OsmRawWayRow.highway.is_not(None))
    )
    if not recompute:
        stmt = stmt.outerjoin(
            WayLandcoverRow, WayLandcoverRow.osm_way_id == OsmRawWayRow.osm_way_id
        ).where(
            or_(
                WayLandcoverRow.osm_way_id.is_(None),
                and_(
                    WayLandcoverRow.trees_percent.is_(None),
                    or_(
                        WayLandcoverRow.source_raster_set.is_distinct_from(raster_set),
                        WayLandcoverRow.algorithm_version.is_distinct_from(algorithm),
                    ),
                ),
            )
        )
    return stmt.order_by(OsmRawWayRow.geom)


async def _fetch_way_geometries(
    session: AsyncSession, way_ids: list[int]
) -> list[tuple[int, LineString]]:
    """way idから、wayのジオメトリを引く（引けなかったidは含めない）。"""
    stmt = select(OsmRawWayRow.osm_way_id, OsmRawWayRow.geom).where(OsmRawWayRow.osm_way_id.in_(way_ids))
    rows = (await session.execute(stmt)).all()
    geometries = shapely.from_wkb([bytes(row.geom.data) for row in rows])
    return [(row.osm_way_id, geom) for row, geom in zip(rows, geometries)]


def _plan(version: str, raster_set: str, recompute: bool) -> LandcoverPlan:
    return LandcoverPlan(
        label="way",
        logger=logger,
        chunk_size=CHUNK_SIZE,
        empty_warning="対象wayが0件のため更新をスキップします（osm_raw_waysが空、または全件計算済みの可能性）",
        target_stmt=_target_way_ids_stmt(recompute, raster_set, version),
        fetch=_fetch_way_geometries,
        build=lambda key, percentages, stamp: WayLandcover(
            osm_way_id=key,
            percentages=percentages,
            data_source=DATA_SOURCE,
            data_version=stamp.data_version,
            computed_at=stamp.computed_at,
            source_osm_import_run_id=stamp.source_osm_import_run_id,
            algorithm_version=stamp.algorithm_version,
            source_raster_set=stamp.source_raster_set,
        ),
        save=lambda repository, records: repository.save_way_landcover(records),
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
    description="way_landcover事前集計バッチ",
    recompute_help="既存行の有無に関わらず対象way全件を再計算する",
    make_plan=_plan,
    buffer_m=DEFAULT_BUFFER_M,
    inner_m=DEFAULT_INNER_M,
)


if __name__ == "__main__":
    sys.exit(main())
