"""土地被覆の事前集計バッチが共有するラスタ読み出し。

way単位（`precompute_way_landcover.py`）と区間単位（`precompute_edge_landcover.py`）は
母集団だけが違い、「線 → リング → 画素ヒストグラム → 割合」の手順は同一である。ここを
共有しないと、片方だけリング径・無効画素の扱いが変わったときに単位ごとの値が静かに
食い違う（同じ道の同じ場所に別の割合が出る）。

`benchmarks/bench_t919_edge_landcover.py`もここを呼ぶ——計測が別の数え方をすると、
測った差が実装で再現しない。
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import logging
import math
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable, Sequence

import numpy as np
from shapely.geometry import LineString, box
from shapely.geometry.base import BaseGeometry
from sqlalchemy import Select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch._common import (
    batch_session_factory,
    count_targets,
    stream_id_chunks,
    with_derived_data_revision_bump,
)
from app.config import settings
from app.domain.derived_data_versions import landcover_algorithm_version
from app.domain.landcover import LandcoverPercentages, class_percentages, raster_set_fingerprint
from app.infrastructure.proj_data import pin_bundled_proj_data
from app.infrastructure.road_graph_repository import RoadGraphRepository

#: 直近に成功したOSM取込のid。どの取込で計算した行かを残すため、チャンクごとに読む。
LATEST_SUCCEEDED_OSM_RUN_ID_SQL = text("SELECT MAX(id) FROM osm_import_runs WHERE status = 'succeeded'")


@dataclass
class LandcoverTally:
    """値が出なかった理由の内訳と、進捗・完了のログ。

    **この内訳は運用者が見る唯一の手掛かり**（値なしで行は書かれるため、DBを見ても
    「なぜ無いのか」は分からない）。way単位と区間単位で数え方や文面が食い違うと、
    同じ状況を2通りに読むことになる。
    """

    out_of_range: int = 0
    partial_coverage: int = 0
    low_pixels: int = 0
    written: int = 0

    def record(self, measured: "RingMeasurement") -> None:
        """1本ぶんの測定結果を数える（値があれば書込、無ければ理由ごと）。"""
        if measured.percentages is not None:
            self.written += 1
        elif measured.reason is NoValueReason.PARTIAL_COVERAGE:
            self.partial_coverage += 1
        elif measured.reason is NoValueReason.LOW_PIXELS:
            self.low_pixels += 1
        else:
            self.out_of_range += 1

    def add(self, other: "LandcoverTally") -> None:
        self.out_of_range += other.out_of_range
        self.partial_coverage += other.partial_coverage
        self.low_pixels += other.low_pixels
        self.written += other.written

    def log_chunk(self, logger: logging.Logger, index: int, total_chunks: int, elapsed_s: float) -> None:
        logger.info(
            "chunk %d/%d 完了: %d件書込（値なしで記録: 範囲外%d件・境界またぎ%d件・画素不足%d件） elapsed=%.1fs",
            index, total_chunks, self.written, self.out_of_range, self.partial_coverage,
            self.low_pixels, elapsed_s,
        )

    def log_completion(self, logger: logging.Logger, label: str, target_count: int, elapsed_s: float) -> None:
        # 境界またぎがあった実行はWARNING——ラスタの継ぎ目に当たった道が値を持たないまま
        # 残るため、次の実行までに気づける形にする。
        log = logger.warning if self.partial_coverage else logger.info
        log(
            "%s土地被覆事前計算完了: 対象=%d件 書込=%d件 値なしで記録（範囲外=%d件 境界またぎ=%d件 "
            "画素不足=%d件） elapsed=%.1fs",
            label, target_count, self.written, self.out_of_range, self.partial_coverage,
            self.low_pixels, elapsed_s,
        )


@dataclass(frozen=True)
class LandcoverStamp:
    """書き込む行に共通して押す素性（どのラスタ・どの版・いつ・どの取込で計算したか）。"""

    data_version: str
    computed_at: "dt.datetime"
    source_osm_import_run_id: int
    algorithm_version: str
    source_raster_set: str


@dataclass(frozen=True)
class LandcoverPlan:
    """way単位と区間単位の違いを、ここへ閉じ込める。

    **母集団だけが違い、手順は同一**というのがこのモジュールの前提
    （冒頭のdocstring参照）。手順の側を2本持つと、その前提が黙って崩れる。
    """

    #: ログに出す単位の呼び名（「way」「区間」）。
    label: str
    #: 進捗・完了を出すlogger（バッチごとに名前が違う）。
    logger: "logging.Logger"
    #: 1チャンクで扱う鍵の数。
    chunk_size: int
    #: 対象が0件だったときの警告文。0件の理由は母集団ごとに違う。
    empty_warning: str
    #: 対象の鍵を選ぶSELECT（`stream_id_chunks`が分割して流す）。
    target_stmt: "Select"
    #: 鍵のチャンク → (鍵, 線) の並び。引けなかった鍵は含めない。
    fetch: "Callable[[AsyncSession, list], Awaitable[Sequence[tuple[object, LineString]]]]"
    #: (鍵, 割合[値なしはNone], 素性) → 書き込む行。
    build: "Callable[[object, LandcoverPercentages | None, LandcoverStamp], object]"
    #: 行の並び → 保存。
    save: "Callable[[RoadGraphRepository, list], Awaitable[None]]"
    #: 計算の前に1回だけ行う後始末（省略可）。母集団から外れた行の回収など。
    prepare: "Callable[..., Awaitable[None]] | None" = None


async def run_landcover_batch(
    make_plan: "Callable[[str, str, bool], LandcoverPlan]",
    database_url: str | None,
    raster_paths: list[str],
    buffer_m: float,
    inner_m: float,
    data_version: str | None,
    recompute: bool,
    dry_run: bool,
) -> int:
    """土地被覆バッチの本体（way単位・区間単位で共通）。引数はCLIの並びそのもの。

    対象をチャンクで流し、リングを測って書き込む。**値が出なかった行も書く**——残さないと、
    増分実行が毎回同じ対象をラスタ読み込みからやり直す。材料としての扱いは行が無い場合と
    同じ欠損のまま。

    `make_plan`は（アルゴリズム版, ラスタ指紋, 増分実行か）から母集団ごとの違いを組み立てる。
    増分実行の対象判定にアルゴリズム版とラスタ指紋が要るため、**ラスタが要らないdry-runでも
    先に決める**（`--raster`無しの
    dry-runは指紋が空集合になり、値なし行を全件対象と数える）。
    """
    started = time.perf_counter()
    version = landcover_algorithm_version(inner_m, buffer_m)
    raster_set = raster_set_fingerprint(raster_paths)
    plan = make_plan(version, raster_set, recompute)
    logger = plan.logger
    chunk_size = plan.chunk_size
    algorithm_version = version
    async with batch_session_factory(database_url) as session_factory:
        if plan.prepare is not None and not dry_run:
            await plan.prepare(session_factory)
        target_count = await count_targets(session_factory, plan.target_stmt)

        logger.info("対象%s数: %d件（chunk_size=%d）", plan.label, target_count, chunk_size)
        if dry_run:
            logger.info("dry-run完了: DB書き込み・ラスタ読み込みなし elapsed=%.1fs", time.perf_counter() - started)
            return 0
        if target_count == 0:
            logger.warning(plan.empty_warning)
            return 0
        total_chunks = math.ceil(target_count / chunk_size)
        sources, resolved_data_version = prepare_raster_run(raster_paths, data_version)
        try:
            now = dt.datetime.now(dt.timezone.utc)
            total = LandcoverTally()
            chunk_index = -1
            async for chunk in stream_id_chunks(session_factory, plan.target_stmt, chunk_size):
                chunk_index += 1
                chunk_started = time.perf_counter()
                tally = LandcoverTally()
                async with session_factory() as session:
                    pairs = await plan.fetch(session, chunk)
                    stamp = LandcoverStamp(
                        data_version=resolved_data_version,
                        computed_at=now,
                        source_osm_import_run_id=(
                            await session.execute(LATEST_SUCCEEDED_OSM_RUN_ID_SQL)
                        ).scalar_one(),
                        algorithm_version=algorithm_version,
                        source_raster_set=raster_set,
                    )
                    records = []
                    for key, line in pairs:
                        measured = measure_ring(sources, line, inner_m, buffer_m)
                        tally.record(measured)
                        records.append(plan.build(key, measured.percentages, stamp))

                    await plan.save(RoadGraphRepository(session), records)
                    await session.commit()

                tally.log_chunk(logger, chunk_index + 1, total_chunks, time.perf_counter() - chunk_started)
                total.add(tally)

            total.log_completion(logger, plan.label, target_count, time.perf_counter() - started)
            return 0
        finally:
            for source in sources:
                source.close()


def prepare_raster_run(
    raster_paths: list[str], data_version: str | None
) -> tuple[list["RasterSource"], str]:
    """ラスタを開き、記録する年（`data_version`）を確定させる。

    **開く前に年を確定させる**——ファイル名から推定できないまま走ると、どの年のラスタで
    計算した行なのかが後から分からなくなる。呼び出し側は`finally`で`close()`する。
    """
    if not raster_paths:
        raise ValueError("--rasterが1件も指定されていません（dry-run以外では必須）")
    resolved_data_version = data_version or infer_data_version_from_filename(raster_paths[0])
    if not resolved_data_version:
        raise ValueError("--data-versionが未指定で、ファイル名からも推定できませんでした")
    return [RasterSource(path) for path in raster_paths], resolved_data_version


#: 母集団ごとの違いを組み立てる関数（アルゴリズム版・ラスタ指紋・増分実行か → プラン）。
#: **各バッチが持つのはこれ1つ**で、実行の手順は共有側にある。
MakePlan = Callable[[str, str, bool], "LandcoverPlan"]


async def run_with_configured_rasters(
    make_plan: "MakePlan", database_url: str | None, dry_run: bool, *, buffer_m: float, inner_m: float
) -> int:
    """`refresh_derived.py`（`(database_url, dry_run)`の統一シグネチャ）向けの薄いラッパー。

    ラスタパスは`settings.lulc_raster_paths_list`から読み、既定のリング径・増分実行
    （`--recompute`無し相当）を使う。dry-run以外でラスタパスが未設定なら失敗させる
    ——黙って飛ばすと「バッチ未実行で軸が静かに欠落する」既知の障害モードを再生産する
    （呼び出し元はラスタ未整備の環境向けに`--skip-landcover`でこの段自体を飛ばせる）。
    """
    raster_paths = settings.lulc_raster_paths_list
    if not raster_paths and not dry_run:
        raise ValueError(
            "settings.lulc_raster_paths（環境変数LULC_RASTER_PATHS）が未設定です。"
            "ラスタを用意できない環境ではrefresh_derived.pyの--skip-landcoverを使ってください。"
        )
    return await run_landcover_batch(
        make_plan, database_url, raster_paths, buffer_m, inner_m, None, False, dry_run
    )


def landcover_batch_main(
    argv: list[str] | None = None,
    *,
    description: str,
    recompute_help: str,
    make_plan: "MakePlan",
    buffer_m: float,
    inner_m: float,
) -> int:
    """土地被覆バッチのCLI。way単位・区間単位で**母集団以外は同じ**ため引数も同じ。

    片側だけに引数が増えると、同じつもりで実行した2本が違う条件で走る。
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--raster", action="append", default=[], help="Esri LULC GeoTIFFのパス（複数指定可）")
    parser.add_argument("--buffer-m", type=float, default=buffer_m, help="リング外径(m)")
    parser.add_argument("--inner-m", type=float, default=inner_m, help="リング内径・道路面除外幅(m)")
    parser.add_argument("--data-version", default=None, help="使用したラスタの年（省略時はファイル名から推定）")
    parser.add_argument("--recompute", action="store_true", help=recompute_help)
    parser.add_argument("--dry-run", action="store_true", help="対象件数のみログ出力しDB書き込み・ラスタ読み込みを行わない")
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(
        with_derived_data_revision_bump(
            run_landcover_batch(
                make_plan,
                args.database_url,
                args.raster,
                args.buffer_m,
                args.inner_m,
                args.data_version,
                args.recompute,
                args.dry_run,
            ),
            database_url=args.database_url,
            dry_run=args.dry_run,
        )
    )

# ファイル名から年次マップの年を抽出する。配布元で命名が2通りある
# （docs/tasks/T624.md「データ取得」参照）。
#   AWS S3 `s3://io-10m-annual-lulc/`  : 54S_2024.tif（年だけ）
#   Azure Blob / Planetary Computer    : 54S_20250101-20260101.tif（期間表記）
# どちらも`_`の直後の4桁が年で、期間表記はその後ろへ続く。
_DATA_VERSION_FROM_FILENAME_RE = re.compile(r"_(\d{4})(?:\d{4}-\d{8})?\.")


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

    PROJデータの固定（`pin_bundled_proj_data`）は`RasterSource.__init__`が済ませている
    前提（線×ラスタごとに呼ぶとその回数だけstat syscallを発行するだけになる）。"""
    # このモジュールはALGORITHM_VERSION参照のためだけにderived_data_freshness.py経由でも
    # importされうる。そちらから読めなくならないよう、ラスタ処理の依存はここでのみ読み込む
    # （モジュール冒頭でimportしない）。`RasterSource`が使うpyprojは
    # requirements-batch.txt限定で、本番webイメージには無い。
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


class NoValueReason(Enum):
    """割合を出せなかった理由。呼び出し元はこれを内訳として数える。

    `PARTIAL_COVERAGE`（ラスタ境界またぎ）と`OUT_OF_RANGE`を分けるのは、前者がラスタの
    追加で解消できるため。
    """

    OUT_OF_RANGE = "out_of_range"
    PARTIAL_COVERAGE = "partial_coverage"
    LOW_PIXELS = "low_pixels"


@dataclass(frozen=True, slots=True)
class RingMeasurement:
    """1本の線ぶんの測定結果。`percentages`がNoneのとき`reason`が理由を持つ。"""

    percentages: LandcoverPercentages | None
    reason: NoValueReason | None


class RasterSource:
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


def measure_ring(
    sources: list[RasterSource], line_wgs84: LineString, inner_m: float, buffer_m: float
) -> RingMeasurement:
    """線1本ぶんの割合を、リングを完全に含む最初のラスタから出す。

    どのラスタもリングを完全には覆えなかった場合、部分的にでも重なるラスタがあったか
    （ラスタ境界をまたぐ線）で理由を分ける。
    """
    partially_covered = False
    for source in sources:
        ring = build_ring(source.to_raster_crs(line_wgs84), inner_m, buffer_m)
        if not source.contains(ring):
            partially_covered = partially_covered or source.intersects(ring)
            continue
        counts = count_pixels_in_ring(source.dataset, ring)
        if counts is None:
            continue
        percentages = class_percentages(counts)
        if percentages is None:
            return RingMeasurement(None, NoValueReason.LOW_PIXELS)
        return RingMeasurement(percentages, None)
    return RingMeasurement(
        None, NoValueReason.PARTIAL_COVERAGE if partially_covered else NoValueReason.OUT_OF_RANGE
    )
