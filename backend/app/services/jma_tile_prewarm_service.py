"""JMA動的タイルの定期プリウォームバッチ。

「1度も見ていない範囲への初回アクセス」はレート制限の対象になる。本バッチは
「アプリの実運用範囲（`WIND_GRID_BBOX`）でよく使われるレイヤー・ズームのタイルを
あらかじめRedisへ温めておく」ことで、通常の利用パターンでは初回アクセスすら
オンデマンドフェッチにならない状態を目指す（`jma_amedas_service.py`の定期更新と
同じ発想、`main.py`のAPSchedulerジョブとして登録する）。

**対象範囲の設計判断**:
- 地理範囲は`WIND_GRID_BBOX`（関東本土、アプリの実運用範囲を表す既存定数）を流用する。
- ズーム範囲は`domain/jma_tile_specs.py: effective_max_zoom`が配信元仕様（`zoomUse`・
  `maxNativeZoom`）から導出する。それを超えるズームではMapLibreがクライアント側でタイルを
  拡大表示するだけで追加の通信が発生しないため、実データの上限がそのままプリウォームの
  上限になる。frontendの`maxzoom`も同じ値を同じレジストリから受け取るため、両者がずれない。
- キキクル3種・線状降水帯予測マップは未来方向のフレームを持たず「現在」の1エントリのみ
  （`riskMap.ts`のコメント参照）だが、雷/竜巻ナウキャストは最大60分先までの予測フレームを
  10分刻みで複数持つ（`thunderNowcast.ts`のコメント参照）。全フレームをプリウォームすると
  タイル数が7倍近くに膨らむため、雷/竜巻も「現在（直近の実況フレーム）」の1件だけを対象に
  する——未来フレームを表示中にパンした場合は引き続きオンデマンドフェッチになるが、雷/竜巻は
  副次的な警告表示（`thunderNowcast.ts`「回避一択の危険」節参照）であり、風・勾配のような
  常時評価軸には使われないため許容する。
"""

import asyncio
import json
import logging
import time

from app.domain.jma_tile_specs import JMA_TILE_SPECS, has_native_tile, max_zoom_for
from app.domain.region import BoundingBox, tiles_covering_bbox
from app.domain.wind_grid import WIND_GRID_BBOX
from app.infrastructure.jma_tile_client import JmaTileClient

logger = logging.getLogger("app.services.jma_tile_prewarm_service")

_PREWARM_BBOX = BoundingBox(
    min_latitude=WIND_GRID_BBOX[1],
    min_longitude=WIND_GRID_BBOX[0],
    max_latitude=WIND_GRID_BBOX[3],
    max_longitude=WIND_GRID_BBOX[2],
)
_MIN_ZOOM = 4
# 同時実行数の上限。JMA非公式APIへ配慮しつつ、約2,000タイルを定期実行の間隔（10分）内に
# 現実的な時間で終えられる値として選んだ（basemap_client.py等の同時実行制御と同じ発想）。
_MAX_CONCURRENCY = 8


class _PrewarmLayer:
    def __init__(self, label: str, group: str, element_id: str, extension: str, target_times_path: str):
        self.label = label
        self.group = group
        self.element_id = element_id
        self.extension = extension
        self.target_times_path = target_times_path

    @property
    def max_zoom(self) -> int:
        """対象ズームの上限。`domain/jma_tile_specs.py`から導出し、ここでは持たない
        （配信元の`zoomUse`・`maxNativeZoom`との突き合わせを1箇所に集めるため）。"""
        return max_zoom_for(self.element_id) or _MIN_ZOOM


_RISK_TARGET_TIMES = "bosai/jmatile/data/risk/targetTimes.json"
_RASRF_TARGET_TIMES = "bosai/jmatile/data/rasrf/targetTimes.json"
_NOWC_TARGET_TIMES = "bosai/jmatile/data/nowc/targetTimes_N3.json"

# frontend側のレイヤー定義（riskMap.ts/thunderNowcast.ts、MapView.tsx: DYNAMIC_WEATHER_
# RENDERERS）と1対1対応させる。対象ズームは各要素の`max_zoom`（jma_tile_specs.pyが
# 配信元仕様から導出）を使う。
_LAYERS: tuple[_PrewarmLayer, ...] = (
    _PrewarmLayer("キキクル・土砂", "risk", "land", "png", _RISK_TARGET_TIMES),
    _PrewarmLayer("キキクル・大雨", "risk", "rain_mesh", "png", _RISK_TARGET_TIMES),
    _PrewarmLayer("キキクル・浸水", "risk", "inund", "png", _RISK_TARGET_TIMES),
    _PrewarmLayer("キキクル・洪水", "risk", "flood", "pbf", _RISK_TARGET_TIMES),
    _PrewarmLayer("線状降水帯予測マップ", "rasrf", "sjfcstmap", "png", _RASRF_TARGET_TIMES),
    _PrewarmLayer("雷ナウキャスト", "nowc", "thns", "png", _NOWC_TARGET_TIMES),
    _PrewarmLayer("竜巻ナウキャスト", "nowc", "trns", "png", _NOWC_TARGET_TIMES),
)


def _pick_current_entry(raw: list[dict], element_id: str | None) -> dict | None:
    """targetTimes.jsonのエントリ群から「現在」を表す1件を選ぶ。

    `element_id`が指定されていれば、`elements`配列にそれを含むエントリへ先に絞り込む
    （risk/rasrf/nowcいずれのグループも共通。nowc、特に雷・竜巻[thns/trns]の
    targetTimes_N3.jsonは5分おきにエントリを持つが、雷・竜巻自体は10分おきにしか更新されず、
    5分ズレたエントリは`elements: ["liden"]`[雷放電位置データのみ]しか持たない。絞り込まずに
    最新basetimeを採用すると、約半分の確率でこのliden-onlyのbasetimeを掴み、存在しない
    タイルを要求し続けて404になる）。絞り込んだ（または`element_id=None`なら絞り込まない）
    候補の中から、直近の実況フレーム（validtime===basetime）のうちbasetime最大のものを
    返す（`jmaNowcastFrames.ts: latestObservedFrameIndex`と同じ「最新の実況」の考え方。
    観測フレームが1件も無ければ予測フレームを含む全候補の中から最大basetimeを返す）。
    """
    candidates = raw
    if element_id is not None:
        candidates = [e for e in raw if element_id in e.get("elements", [])]
    observed = [e for e in candidates if e.get("validtime") == e.get("basetime")]
    pool = observed if observed else candidates
    if not pool:
        return None
    return max(pool, key=lambda e: e["basetime"])


def _tile_paths_for_layer(layer: "_PrewarmLayer", entry: dict) -> list[str]:
    basetime = entry["basetime"]
    validtime = entry["validtime"]
    # nowc系のtargetTimes.jsonはmemberを持たない（frontend: thunderNowcast.tsが"none"を
    # 直書きしているのと同じ理由）。risk/rasrfはエントリ自体にmemberを持つ。
    member = entry.get("member", "none") if layer.group != "nowc" else "none"
    paths = []
    spec = JMA_TILE_SPECS.get(layer.element_id)
    for z in range(_MIN_ZOOM, layer.max_zoom + 1):
        # 配信元が実データを持たないズーム（zoomUseの偶奇に合わない段）は温めても空タイル
        # しか積まれない。要求されたときは親から補間するため（infrastructure/
        # jma_tile_interpolation.py）、親側さえ温まっていればよい。
        if spec is not None and not has_native_tile(spec, z):
            continue
        for x, y in tiles_covering_bbox(_PREWARM_BBOX, z):
            paths.append(
                f"bosai/jmatile/data/{layer.group}/{basetime}/{member}/{validtime}/surf/"
                f"{layer.element_id}/{z}/{x}/{y}.{layer.extension}"
            )
    return paths


async def prewarm_jma_tiles(client: JmaTileClient) -> None:
    """対象範囲のタイルを列挙し、`JmaTileClient.get()`で順に取得する（Redisへの書き込みは
    `get()`内部の副作用として自動的に起きる。プリウォーム専用の別書き込み経路は持たない）。
    既にRedisへ温まっているタイルはキャッシュヒットで即座に返るため、実行のたびに毎回
    フルフェッチするわけではない。"""
    started = time.monotonic()
    target_times_cache: dict[str, list[dict] | None] = {}
    all_paths: list[str] = []
    skipped_labels: list[str] = []

    for layer in _LAYERS:
        if layer.target_times_path not in target_times_cache:
            raw = await client.get(layer.target_times_path)
            if raw is None:
                target_times_cache[layer.target_times_path] = None
            else:
                content, _content_type = raw
                try:
                    target_times_cache[layer.target_times_path] = json.loads(content)
                except (ValueError, TypeError):
                    target_times_cache[layer.target_times_path] = None
        raw_entries = target_times_cache[layer.target_times_path]
        if not raw_entries:
            skipped_labels.append(layer.label)
            continue
        # 絞り込みの理由は_pick_current_entryのdocstring参照。全グループで一律に
        # layer.element_idへ揃える。
        entry = _pick_current_entry(raw_entries, layer.element_id)
        if entry is None:
            skipped_labels.append(layer.label)
            continue
        all_paths.extend(_tile_paths_for_layer(layer, entry))

    if skipped_labels:
        logger.warning("jma tile prewarm: targetTimes取得/解析に失敗しスキップ labels=%s", skipped_labels)

    fetched = 0
    errors = 0
    total_bytes = 0
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _fetch_one(path: str) -> None:
        nonlocal fetched, errors, total_bytes
        async with semaphore:
            result = await client.get(path)
        if result is None:
            errors += 1
        else:
            fetched += 1
            total_bytes += len(result[0])

    await asyncio.gather(*(_fetch_one(path) for path in all_paths))

    elapsed_ms = round((time.monotonic() - started) * 1000)
    logger.info(
        "jma tile prewarm 完了 tiles=%d fetched=%d errors=%d total_bytes=%d elapsed_ms=%d",
        len(all_paths),
        fetched,
        errors,
        total_bytes,
        elapsed_ms,
    )
