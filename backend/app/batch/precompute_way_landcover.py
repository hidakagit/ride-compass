"""way_landcoverの事前集計バッチ。

道路centerline（`osm_raw_ways.geom`）の周囲100mリング（既定、`--buffer-m`/`--inner-m`で
変更可）内の土地被覆クラス別画素数を、Esri×Impact ObservatoryのGeoTIFF（`--raster`で
指定、複数ファイル可）から`rasterio`で読み取り、`domain/landcover.py: class_percentages`で
割合(%)へ変換して`way_landcover`へUPSERTする。母集団は`osm_raw_ways`全域
（geom・highwayを持つway）で、Road Graph（road_edges）には依存しない
（`precompute_way_attribute_counts.py`と同じ理由）。

ラスタファイルはリポジトリにコミットしない（手動取得、docs/disaster-recovery.md参照）。
複数ファイルを渡した場合、各wayは重心を含む最初のファイルで処理する（`--recompute`
無しなら`way_landcover`に未だ行が無いwayだけを対象にする増分実行）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.precompute_way_landcover --raster <path>
    --dry-runで対象件数のログのみ（DB書き込み・ラスタ読み込みなし）
"""

import argparse
import asyncio
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.batch._common import chunked
from app.config import settings
from app.domain.landcover import WayLandcover, class_percentages
from app.infrastructure.road_graph_models import OsmRawWayRow, WayLandcoverRow
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("app.batch.precompute_way_landcover")

CHUNK_SIZE = 5_000
DEFAULT_BUFFER_M = 100.0
DEFAULT_INNER_M = 10.0
DATA_SOURCE = "esri-io-lulc"

_LATEST_SUCCEEDED_OSM_RUN_ID_SQL = text("SELECT MAX(id) FROM osm_import_runs WHERE status = 'succeeded'")

# ファイル名（例: 54S_20250101-20260101.tif）から開始年を抽出する。Azure Blob/Planetary
# Computerの配布規約に合わせた命名（docs/tasks/T624.md「データ取得」参照）。
_DATA_VERSION_FROM_FILENAME_RE = re.compile(r"(\d{4})\d{4}-\d{8}")


def algorithm_version(inner_m: float, buffer_m: float) -> str:
    return f"v1-ring{int(inner_m)}-{int(buffer_m)}"


# 派生データ鮮度台帳（derived_data_freshness.py: GENERATION_FRESHNESS_SPECS）が参照する
# 「現在の既定リング径」の版数。--buffer-m/--inner-mでこれと異なる値を指定して実行すると、
# 鮮度台帳はその行を古い版として検知する（`algorithm_version`関数のとおり径ごとに
# 版文字列が変わるため）。
ALGORITHM_VERSION = algorithm_version(DEFAULT_INNER_M, DEFAULT_BUFFER_M)


def infer_data_version_from_filename(path: str) -> str | None:
    match = _DATA_VERSION_FROM_FILENAME_RE.search(Path(path).name)
    return match.group(1) if match else None


def build_ring(line: LineString, inner_m: float, outer_m: float) -> BaseGeometry:
    """道路centerline（ラスタと同じ投影CRS）から、外側`outer_m`m・内側`inner_m`mの
    リングを作る。道路面自体の画素を除くため中心線をそのまま使わず内側を刳り貫く
    （理由はdocs/tasks/T624.md論点1「道路自身の画素を除くリング形状にする理由」参照）。"""
    return line.buffer(outer_m).difference(line.buffer(inner_m))


def count_pixels_in_ring(dataset, ring: BaseGeometry) -> dict[int, int] | None:
    """開いているラスタ`dataset`（`ring`と同じCRS）から、`ring`内画素のクラス値
    ヒストグラムを返す。`ring`がラスタ範囲と重ならない場合はNone（このデータセットの
    対象外、呼び出し元が他のラスタを試すか諦める）。"""
    # rasterioはrequirements-batch.txt限定の依存で本番webイメージには無いため、この
    # モジュールをALGORITHM_VERSION参照のためだけにimportするderived_data_freshness.py
    # 経由でもimportできるよう、ここでのみ読み込む（モジュール冒頭でimportしない）。
    import rasterio.errors
    import rasterio.features

    if ring.is_empty:
        return {}
    try:
        window = rasterio.features.geometry_window(dataset, [ring])
    except rasterio.errors.WindowError:
        return None
    if window.width <= 0 or window.height <= 0:
        return None
    data = dataset.read(1, window=window)
    if data.size == 0:
        return None
    window_transform = dataset.window_transform(window)
    mask = rasterio.features.geometry_mask([ring], out_shape=data.shape, transform=window_transform, invert=True)
    values, counts = np.unique(data[mask], return_counts=True)
    return {int(value): int(count) for value, count in zip(values, counts)}


async def _fetch_target_way_ids(session: AsyncSession, recompute: bool) -> list[int]:
    """対象way（geom・highwayを持つ）のosm_way_idを地理的順序で返す。`recompute=False`
    （既定）では`way_landcover`に既に行があるwayをanti-joinで除外する増分実行
    （`precompute_elevation_attributes.py`と同じ考え方）。"""
    stmt = (
        select(OsmRawWayRow.osm_way_id)
        .where(OsmRawWayRow.geom.is_not(None))
        .where(OsmRawWayRow.highway.is_not(None))
    )
    if not recompute:
        stmt = stmt.outerjoin(WayLandcoverRow, WayLandcoverRow.osm_way_id == OsmRawWayRow.osm_way_id).where(
            WayLandcoverRow.osm_way_id.is_(None)
        )
    stmt = stmt.order_by(OsmRawWayRow.geom)
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def _fetch_way_geometries(session: AsyncSession, way_ids: list[int]) -> dict[int, LineString]:
    stmt = select(OsmRawWayRow.osm_way_id, OsmRawWayRow.geom).where(OsmRawWayRow.osm_way_id.in_(way_ids))
    rows = (await session.execute(stmt)).all()
    way_ids_ordered = [row.osm_way_id for row in rows]
    geometries = shapely.from_wkb([bytes(row.geom.data) for row in rows])
    return dict(zip(way_ids_ordered, geometries))


class _RasterSource:
    """1つのラスタファイル（開いたままの`rasterio.DatasetReader`）と、
    EPSG:4326からそのラスタのCRSへの変換器を束ねる。"""

    def __init__(self, path: str):
        # count_pixels_in_ringと同じ理由でここでのみimportする。
        import pyproj
        import rasterio

        self.dataset = rasterio.open(path)
        self._transformer = pyproj.Transformer.from_crs("EPSG:4326", self.dataset.crs, always_xy=True)

    def to_raster_crs(self, line_wgs84: LineString) -> LineString:
        return LineString(self._transformer.itransform(line_wgs84.coords))

    def close(self) -> None:
        self.dataset.close()


async def run(
    database_url: str | None,
    raster_paths: list[str],
    buffer_m: float,
    inner_m: float,
    data_version: str | None,
    recompute: bool,
    dry_run: bool,
) -> int:
    started = time.perf_counter()
    engine = create_async_engine(database_url or settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            way_ids = await _fetch_target_way_ids(session, recompute)

        logger.info("対象way数: %d件（chunk_size=%d）", len(way_ids), CHUNK_SIZE)
        if dry_run:
            logger.info("dry-run完了: DB書き込み・ラスタ読み込みなし elapsed=%.1fs", time.perf_counter() - started)
            return 0
        if not way_ids:
            logger.warning("対象wayが0件のため更新をスキップします（osm_raw_waysが空、または全件計算済みの可能性）")
            return 0
        if not raster_paths:
            raise ValueError("--rasterが1件も指定されていません（dry-run以外では必須）")

        resolved_data_version = data_version or infer_data_version_from_filename(raster_paths[0])
        if not resolved_data_version:
            raise ValueError("--data-versionが未指定で、ファイル名からも推定できませんでした")

        version = algorithm_version(inner_m, buffer_m)
        sources = [_RasterSource(path) for path in raster_paths]
        try:
            now = datetime.now(timezone.utc)
            total_written = 0
            total_out_of_range = 0
            total_low_pixels = 0
            chunks = chunked(way_ids, CHUNK_SIZE)
            for chunk_index, chunk in enumerate(chunks):
                chunk_started = time.perf_counter()
                async with session_factory() as session:
                    geometries = await _fetch_way_geometries(session, chunk)
                    source_osm_import_run_id = (await session.execute(_LATEST_SUCCEEDED_OSM_RUN_ID_SQL)).scalar_one()

                    records: list[WayLandcover] = []
                    for way_id in chunk:
                        line = geometries.get(way_id)
                        if line is None:
                            continue
                        percentages = None
                        for source in sources:
                            ring = build_ring(source.to_raster_crs(line), inner_m, buffer_m)
                            counts = count_pixels_in_ring(source.dataset, ring)
                            if counts is not None:
                                percentages = class_percentages(counts)
                                break
                        else:
                            total_out_of_range += 1
                            continue
                        if percentages is None:
                            total_low_pixels += 1
                            continue
                        records.append(
                            WayLandcover(
                                osm_way_id=way_id,
                                percentages=percentages,
                                data_source=DATA_SOURCE,
                                data_version=resolved_data_version,
                                computed_at=now,
                                source_osm_import_run_id=source_osm_import_run_id,
                                algorithm_version=version,
                            )
                        )

                    repository = RoadGraphRepository(session)
                    await repository.save_way_landcover(records)
                    await session.commit()

                total_written += len(records)
                logger.info(
                    "chunk %d/%d 完了: %d件書込（範囲外%d件・画素不足%d件） elapsed=%.1fs",
                    chunk_index + 1, len(chunks), len(records), total_out_of_range, total_low_pixels,
                    time.perf_counter() - chunk_started,
                )

            logger.info(
                "土地被覆事前計算完了: 対象=%d件 書込=%d件 範囲外=%d件 画素不足=%d件 elapsed=%.1fs",
                len(way_ids), total_written, total_out_of_range, total_low_pixels,
                time.perf_counter() - started,
            )
            return 0
        finally:
            for source in sources:
                source.close()
    finally:
        await engine.dispose()


async def run_default(database_url: str | None, dry_run: bool) -> int:
    """`refresh_derived.py`（`(database_url, dry_run)`の統一シグネチャで各段を呼ぶ）向けの
    薄いラッパー。ラスタパスは`settings.lulc_raster_paths_list`から読み、既定のリング径
    （`DEFAULT_INNER_M`/`DEFAULT_BUFFER_M`）・増分実行（`--recompute`無し相当）を使う。
    dry-run以外でラスタパスが未設定なら失敗させる（黙って飛ばすと「バッチ未実行で軸が
    静かに欠落する」既知の障害モードを再生産するため。呼び出し元の`refresh_derived.py`が
    ラスタ未整備の環境向けに`--skip-landcover`でこの段自体をスキップする経路を持つ）。"""
    raster_paths = settings.lulc_raster_paths_list
    if not raster_paths and not dry_run:
        raise ValueError(
            "settings.lulc_raster_paths（環境変数LULC_RASTER_PATHS）が未設定です。"
            "ラスタを用意できない環境ではrefresh_derived.pyの--skip-landcoverを使ってください。"
        )
    return await run(database_url, raster_paths, DEFAULT_BUFFER_M, DEFAULT_INNER_M, None, False, dry_run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="way_landcover事前集計バッチ")
    parser.add_argument("--raster", action="append", default=[], help="Esri LULC GeoTIFFのパス（複数指定可）")
    parser.add_argument("--buffer-m", type=float, default=DEFAULT_BUFFER_M, help="リング外径(m)")
    parser.add_argument("--inner-m", type=float, default=DEFAULT_INNER_M, help="リング内径・道路面除外幅(m)")
    parser.add_argument("--data-version", default=None, help="使用したラスタの年（省略時はファイル名から推定）")
    parser.add_argument("--recompute", action="store_true", help="既存行の有無に関わらず対象way全件を再計算する")
    parser.add_argument("--dry-run", action="store_true", help="対象件数のみログ出力しDB書き込み・ラスタ読み込みを行わない")
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(
        run(
            args.database_url,
            args.raster,
            args.buffer_m,
            args.inner_m,
            args.data_version,
            args.recompute,
            args.dry_run,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
