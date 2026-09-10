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

import argparse
import asyncio
import hashlib
import logging
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, box
from shapely.geometry.base import BaseGeometry
from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch._common import batch_session_factory, count_targets, stream_id_chunks
from app.config import settings
from app.domain.landcover import WayLandcover, class_percentages
from app.infrastructure.proj_data import pin_bundled_proj_data
from app.infrastructure.road_graph_models import OsmRawWayRow, WayLandcoverRow
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.precompute_way_landcover")

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
    対象外、呼び出し元が他のラスタを試すか諦める）。

    PROJデータの固定（`pin_bundled_proj_data`）は`_RasterSource.__init__`が済ませている
    前提（way×ラスタごとに呼ぶとその回数だけstat syscallを発行するだけになる）。"""
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


def raster_set_fingerprint(raster_paths: list[str]) -> str:
    """ラスタ構成の指紋（ファイル名の集合から決まる短い文字列）。

    「値なし」の行はこの構成でそう確定したという意味しか持たない——ラスタを1枚足せば、
    境界またぎ・範囲外だったwayは値を持ちうる。指紋が変われば増分実行がその行を対象へ
    戻すことで、ラスタ追加後の取りこぼしを防ぐ。順序には依存させない（同じ集合を
    どの順で渡しても同じ指紋になる）。
    """
    joined = "\n".join(sorted(Path(path).name for path in raster_paths))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


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
        pin_bundled_proj_data()
        import pyproj
        import rasterio

        self.dataset = rasterio.open(path)
        self._bounds = box(*self.dataset.bounds)
        self._transformer = pyproj.Transformer.from_crs("EPSG:4326", self.dataset.crs, always_xy=True)

    def to_raster_crs(self, line_wgs84: LineString) -> LineString:
        return LineString(self._transformer.itransform(line_wgs84.coords))

    def contains(self, ring: BaseGeometry) -> bool:
        """`ring`（このラスタのCRS）が範囲へ完全に収まるか。

        一部だけ重なるラスタで割合を出すと、重なった側の土地被覆だけで100%を分け合う
        「もっともらしい値」になり、NULLではないため鮮度台帳にも欠損として現れない。
        画素数ではなく矩形の包含で判定するのは、リング形状のラスタライズ誤差に
        依存させないため。"""
        return self._bounds.contains(ring)

    def intersects(self, ring: BaseGeometry) -> bool:
        return self._bounds.intersects(ring)

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
    # 増分実行の対象判定に指紋・アルゴリズム版が要るため、ラスタが要らないdry-runでも
    # 先に決める（`--raster`無しのdry-runは指紋が空集合になり、値なし行を全件対象と数える）。
    version = algorithm_version(inner_m, buffer_m)
    raster_set = raster_set_fingerprint(raster_paths)
    stmt = _target_way_ids_stmt(recompute, raster_set, version)
    async with batch_session_factory(database_url) as session_factory:
        target_count = await count_targets(session_factory, stmt)

        logger.info("対象way数: %d件（chunk_size=%d）", target_count, CHUNK_SIZE)
        if dry_run:
            logger.info("dry-run完了: DB書き込み・ラスタ読み込みなし elapsed=%.1fs", time.perf_counter() - started)
            return 0
        if target_count == 0:
            logger.warning("対象wayが0件のため更新をスキップします（osm_raw_waysが空、または全件計算済みの可能性）")
            return 0
        total_chunks = math.ceil(target_count / CHUNK_SIZE)
        if not raster_paths:
            raise ValueError("--rasterが1件も指定されていません（dry-run以外では必須）")

        resolved_data_version = data_version or infer_data_version_from_filename(raster_paths[0])
        if not resolved_data_version:
            raise ValueError("--data-versionが未指定で、ファイル名からも推定できませんでした")

        sources = [_RasterSource(path) for path in raster_paths]
        try:
            now = datetime.now(timezone.utc)
            total_written = 0
            total_out_of_range = 0
            total_partial_coverage = 0
            total_low_pixels = 0
            chunk_index = -1
            async for chunk in stream_id_chunks(session_factory, stmt, CHUNK_SIZE):
                chunk_index += 1
                chunk_started = time.perf_counter()
                chunk_out_of_range = 0
                chunk_partial_coverage = 0
                chunk_low_pixels = 0
                async with session_factory() as session:
                    geometries = await _fetch_way_geometries(session, chunk)
                    source_osm_import_run_id = (await session.execute(_LATEST_SUCCEEDED_OSM_RUN_ID_SQL)).scalar_one()

                    records: list[WayLandcover] = []

                    def no_value_record(way_id: int) -> WayLandcover:
                        """「この構成では値なし」を表す行（割合列はNULL）。

                        行を残さないと増分実行が毎回同じwayをラスタ読み込みからやり直す。
                        材料としての扱いは行が無い場合と同じ欠損のまま。
                        """
                        return WayLandcover(
                            osm_way_id=way_id,
                            percentages=None,
                            data_source=DATA_SOURCE,
                            data_version=resolved_data_version,
                            computed_at=now,
                            source_osm_import_run_id=source_osm_import_run_id,
                            algorithm_version=version,
                            source_raster_set=raster_set,
                        )

                    for way_id in chunk:
                        line = geometries.get(way_id)
                        if line is None:
                            continue
                        counts = None
                        partially_covered = False
                        for source in sources:
                            ring = build_ring(source.to_raster_crs(line), inner_m, buffer_m)
                            if not source.contains(ring):
                                partially_covered = partially_covered or source.intersects(ring)
                                continue
                            counts = count_pixels_in_ring(source.dataset, ring)
                            if counts is not None:
                                break
                        if counts is None:
                            # 1枚もリングを完全には覆えなかった。部分的にでも重なるラスタが
                            # あった場合（ラスタ境界をまたぐway）と、どのラスタからも外れて
                            # いる場合を区別して数える（前者はラスタの追加で解消できる）。
                            if partially_covered:
                                chunk_partial_coverage += 1
                            else:
                                chunk_out_of_range += 1
                            records.append(no_value_record(way_id))
                            continue
                        percentages = class_percentages(counts)
                        if percentages is None:
                            chunk_low_pixels += 1
                            records.append(no_value_record(way_id))
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
                                source_raster_set=raster_set,
                            )
                        )

                    repository = RoadGraphRepository(session)
                    await repository.save_way_landcover(records)
                    await session.commit()

                # 「書込」は値を持つ行の件数。値なしの行（範囲外・境界またぎ・画素不足）も
                # 同じUPSERTで書くが、内訳の3件数と二重に数えないよう分けて出す。
                chunk_written = len(records) - chunk_out_of_range - chunk_partial_coverage - chunk_low_pixels
                total_written += chunk_written
                total_out_of_range += chunk_out_of_range
                total_partial_coverage += chunk_partial_coverage
                total_low_pixels += chunk_low_pixels
                logger.info(
                    "chunk %d/%d 完了: %d件書込（値なしで記録: 範囲外%d件・境界またぎ%d件・画素不足%d件） elapsed=%.1fs",
                    chunk_index + 1, total_chunks, chunk_written, chunk_out_of_range, chunk_partial_coverage,
                    chunk_low_pixels, time.perf_counter() - chunk_started,
                )

            log_completion = logger.warning if total_partial_coverage else logger.info
            log_completion(
                "土地被覆事前計算完了: 対象=%d件 書込=%d件 値なしで記録（範囲外=%d件 境界またぎ=%d件 "
                "画素不足=%d件） elapsed=%.1fs",
                target_count, total_written, total_out_of_range, total_partial_coverage, total_low_pixels,
                time.perf_counter() - started,
            )
            return 0
        finally:
            for source in sources:
                source.close()


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
