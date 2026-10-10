"""JMA動的タイルの定期プリウォームバッチ。

「1度も見ていない範囲への初回アクセス」はレート制限の対象になる。実運用範囲でよく使われる
レイヤー・ズームをあらかじめRedisへ温めておき、通常の利用では初回アクセスすらオンデマンド
フェッチにならない状態を目指す。

**対象範囲の決め方**:
- 地理範囲はサービスの対象範囲（取り込んだ道路の範囲、`RegionService.get_ingested_area`）。呼び出し元が渡す。
- ズーム上限は`domain/jma_tile_specs.py`が配信元仕様から導出する。それを超えるズームでは
  クライアントがタイルを拡大表示するだけで追加の通信が起きないため、実データの上限が
  そのままプリウォームの上限になる。
- 予測フレームを複数持つ要素でも、温めるのは段ごとに1フレームだけ。全フレームを温めると
  タイル数が桁違いに膨らむ。未来フレームを表示したままパンするとオンデマンドフェッチに戻る。
- 対象の要素は動的気象の要素の宣言（`domain/weather_elements.py: WEATHER_ELEMENTS`）のうち
  タイルで描くものの配信要素すべて。1つのソースが時刻の段ごとに別の配信要素から届く場合
  （降水の`main`）は段ごとに温める。
- 温めるフレームは、時刻一覧を画面と同じ読み方（`read_target_times`）でコマにし、画面と同じつなぎ方
  （`stage_first_frames`）で段をつないだときに各段が最初に描くコマ。画面と同じになることは
  `scripts/cross_language_expectations.py: jma_expectations`の表を画面のテストが通して確かめる。
"""

import asyncio
import logging
import time

from app.domain.jma_tile_specs import (
    JMA_TILE_MIN_ZOOM,
    JmaFrame,
    JmaTile,
    TargetTimesRow,
    effective_max_zoom,
    has_native_tile,
    jma_tile_path,
    jma_tile_spec,
    read_target_times,
    tile_extension,
    with_interpolated_zooms,
)
from app.domain.region import BoundingBox, tiles_covering_bbox
from app.domain.weather_elements import (
    WEATHER_ELEMENTS,
    WeatherDelivery,
    stage_first_frames,
    weather_element_deliveries,
    weather_element_tile,
)
from app.infrastructure.jma_tile_client import EmptyTile, JmaTileClient, get_target_times
from app.infrastructure.jma_tile_content import is_empty_tile
from app.infrastructure.jma_tile_index import JmaTileIndex, JmaTileIndexCoverage, JmaTileIndexElement, set_index

logger = logging.getLogger("ridecompass.jma_tile_prewarm_service")

# 同時実行数の上限。配信元へ配慮しつつ、対象タイル全体を定期実行の間隔内に終えられること。
_MAX_CONCURRENCY = 8


class _PrewarmLayer:
    def __init__(self, label: str, delivery: WeatherDelivery):
        self.label = label
        self.element_id = delivery.element_id
        #: 時刻一覧の読み方。画面へ配る宣言（生成物の`jmaElements`）と同じものを読む。
        self.reader = delivery.reader
        # 配信元仕様は`domain/jma_tile_specs.py`が持つ。ここで引いておくことで、
        # 登録の無い要素idを書いた時点（import時）にKeyErrorで落ちる——既定のズームへ
        # 倒すと、綴り違いのレイヤーが「1段も温まらない」だけで静かに通る。
        self.spec = jma_tile_spec(delivery.element_id)
        self.target_times_paths = delivery.target_times_paths

    @property
    def max_zoom(self) -> int:
        return effective_max_zoom(self.spec)


#: タイルで描く要素ごとの、時刻の段（近い時刻から）。
_STAGES: tuple[tuple[_PrewarmLayer, ...], ...] = tuple(
    tuple(_PrewarmLayer(element.label, delivery) for delivery in weather_element_deliveries(element))
    for element in WEATHER_ELEMENTS
    if weather_element_tile(element) is not None
)


def _tiles_for_layer(layer: _PrewarmLayer, frame: JmaFrame, area: BoundingBox) -> list[JmaTile]:
    tiles = []
    for z in range(JMA_TILE_MIN_ZOOM, layer.max_zoom + 1):
        # 配信元が実データを持たないズーム（zoomUseの偶奇に合わない段）は温めても空タイル
        # しか積まれない。要求されたときは親から補間するため（infrastructure/
        # jma_tile_interpolation.py）、親側さえ温まっていればよい。
        if not has_native_tile(layer.spec, z):
            continue
        for x, y in tiles_covering_bbox(area, z):
            tiles.append(JmaTile(layer.element_id, frame, z, x, y))
    return tiles


async def _store_index(
    area: BoundingBox, layer_frames: dict[str, JmaFrame], present: dict[str, dict[int, list[list[int]]]]
) -> None:
    """在否インデックスを組み立てて保存する。

    クライアントは「自分が描こうとしているフレーム（`basetime`・`validtime`・`member`）と一致する
    要素だけ」インデックスを信用する必要があるため、要素ごとにこの3つを持たせる
    （risk系・nowc系・rasrf系で更新タイミングが別々のため、1つの`basetime`では表せない。
    1つの`basetime`に実況と複数の予測の`validtime`が載るため、`basetime`だけでも表せない）。
    `coverage`はインデックスが網羅している地理範囲で、**この外のタイルについては在否が
    不明なので従来どおり取得する**ことをクライアントへ伝える。
    """
    if not layer_frames:
        return
    index = JmaTileIndex(
        coverage=JmaTileIndexCoverage(
            min_longitude=area.min_longitude,
            min_latitude=area.min_latitude,
            max_longitude=area.max_longitude,
            max_latitude=area.max_latitude,
        ),
        elements={
            element_id: JmaTileIndexElement(
                basetime=frame.basetime,
                validtime=frame.validtime,
                member=frame.member,
                # ズームは文字列キー（JSONのオブジェクトキーは文字列のため、往復で型が
                # 変わらないようにここで揃える）。補間で埋めるズームは親から補う——
                # インデックスに載らないタイルをクライアントは空と見なすので、温めない
                # ズームを載せずにおくと補間（`jma_tile_interpolation.py`）が一度も動かない。
                zooms={
                    str(z): coords
                    for z, coords in sorted(
                        with_interpolated_zooms(element_id, present.get(element_id, {})).items()
                    )
                },
            )
            for element_id, frame in layer_frames.items()
        },
    )
    await set_index(index)


async def prewarm_jma_tiles(client: JmaTileClient, area: BoundingBox) -> None:
    """対象範囲`area`のタイルを列挙し、`JmaTileClient.get()`で取得する。

    Redisへの書き込みは`get()`の副作用で起きる。プリウォーム専用の書き込み経路は持たない
    ——持つと、通常の取得経路とキャッシュの形が分かれる。
    """
    started = time.monotonic()
    target_times_cache: dict[str, list[TargetTimesRow] | None] = {}
    all_tiles: list[JmaTile] = []
    skipped_labels: list[str] = []
    layer_frames: dict[str, JmaFrame] = {}

    for stages in _STAGES:
        stage_frames: list[list[JmaFrame]] = []
        for layer in stages:
            rows: list[TargetTimesRow] = []
            for target_times_path in layer.target_times_paths:
                if target_times_path not in target_times_cache:
                    target_times_cache[target_times_path] = await get_target_times(client, target_times_path)
                rows.extend(target_times_cache[target_times_path] or [])
            stage_frames.append(read_target_times(layer.reader, rows, layer.element_id))
        for layer, frame in zip(stages, stage_first_frames(stage_frames), strict=True):
            if frame is None:
                skipped_labels.append(f"{layer.label}({layer.element_id})")
                continue
            layer_frames[layer.element_id] = frame
            all_tiles.extend(_tiles_for_layer(layer, frame, area))

    if skipped_labels:
        logger.warning("jma tile prewarm: targetTimes取得/解析に失敗しスキップ labels=%s", skipped_labels)

    fetched = 0
    empty = 0
    errors = 0
    total_bytes = 0
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    # 在否インデックス（infrastructure/jma_tile_index.py）。取得したタイルが空かどうかを
    # ここで判定して集める——プリウォームは既に全タイルを取得しているため、判定のための
    # 追加の取得は発生しない。
    present: dict[str, dict[int, list[list[int]]]] = {}

    async def _fetch_one(tile: JmaTile) -> None:
        nonlocal fetched, empty, errors, total_bytes
        async with semaphore:
            result = await client.get(jma_tile_path(tile))
        if result is None:
            errors += 1
            return
        if isinstance(result, EmptyTile):
            # 描くものが無いと確認済み（上流の404、または前回の取得で空と分かってフラグで
            # 保持されているもの）。平常時はこれが大半のため、失敗として数えない。
            empty += 1
            return
        fetched += 1
        content = result[0]
        total_bytes += len(content)
        if is_empty_tile(content, tile_extension(jma_tile_spec(tile.element_id))):
            empty += 1
            return
        present.setdefault(tile.element_id, {}).setdefault(tile.z, []).append([tile.x, tile.y])

    await asyncio.gather(*(_fetch_one(tile) for tile in all_tiles))
    await _store_index(area, layer_frames, present)

    elapsed_ms = round((time.monotonic() - started) * 1000)
    non_empty = sum(len(coords) for zooms in present.values() for coords in zooms.values())
    logger.info(
        "jma tile prewarm 完了 tiles=%d fetched=%d empty=%d errors=%d non_empty=%d total_bytes=%d elapsed_ms=%d",
        len(all_tiles),
        fetched,
        empty,
        errors,
        non_empty,
        total_bytes,
        elapsed_ms,
    )
