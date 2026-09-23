"""JMA動的タイルの定期プリウォームバッチ。

「1度も見ていない範囲への初回アクセス」はレート制限の対象になる。実運用範囲でよく使われる
レイヤー・ズームをあらかじめRedisへ温めておき、通常の利用では初回アクセスすらオンデマンド
フェッチにならない状態を目指す。

**対象範囲の決め方**:
- 地理範囲は`WIND_GRID_BBOX`（アプリの実運用範囲を表す既存定数）を流用する。
- ズーム上限は`domain/jma_tile_specs.py`が配信元仕様から導出する。それを超えるズームでは
  クライアントがタイルを拡大表示するだけで追加の通信が起きないため、実データの上限が
  そのままプリウォームの上限になる。
- 予測フレームを複数持つ要素でも、温めるのは「現在（直近の実況フレーム）」の1件だけ。
  全フレームを温めるとタイル数が桁違いに膨らむ。未来フレームを表示したままパンすると
  オンデマンドフェッチに戻るが、予測フレームを持つのは副次的な警告表示のレイヤーだけで、
  常時評価する軸には使われない。
"""

import asyncio
import json
import logging
import time

from app.domain.jma_tile_specs import (
    JMA_TILE_SPECS,
    effective_max_zoom,
    has_native_tile,
    source_zoom_for_interpolation,
)
from app.domain.region import BoundingBox, tiles_covering_bbox
from app.domain.wind_grid import WIND_GRID_BBOX
from app.infrastructure.jma_tile_client import JmaTileClient
from app.infrastructure.jma_tile_client import EmptyTile
from app.infrastructure.jma_tile_content import is_empty_tile
from app.infrastructure.jma_tile_index import set_index
from app.infrastructure.jma_tile_interpolation import parse_tile_path

logger = logging.getLogger("ridecompass.jma_tile_prewarm_service")

_PREWARM_BBOX = BoundingBox(
    min_latitude=WIND_GRID_BBOX[1],
    min_longitude=WIND_GRID_BBOX[0],
    max_latitude=WIND_GRID_BBOX[3],
    max_longitude=WIND_GRID_BBOX[2],
)
_MIN_ZOOM = 4
# 同時実行数の上限。配信元へ配慮しつつ、対象タイル全体を定期実行の間隔内に終えられること。
_MAX_CONCURRENCY = 8


class _PrewarmLayer:
    def __init__(self, label: str, element_id: str, extension: str, target_times_path: str):
        self.label = label
        self.element_id = element_id
        self.extension = extension
        self.target_times_path = target_times_path
        # 配信元仕様は`domain/jma_tile_specs.py`が持つ。ここで引いておくことで、
        # 登録の無い要素idを書いた時点（import時）にKeyErrorで落ちる——既定のズームへ
        # 倒すと、綴り違いのレイヤーが「1段も温まらない」だけで静かに通る。
        self.spec = JMA_TILE_SPECS[element_id]
        self.group = self.spec.path_group

    @property
    def max_zoom(self) -> int:
        return effective_max_zoom(self.spec)


_RISK_TARGET_TIMES = "bosai/jmatile/data/risk/targetTimes.json"
_RASRF_TARGET_TIMES = "bosai/jmatile/data/rasrf/targetTimes.json"
_NOWC_TARGET_TIMES = "bosai/jmatile/data/nowc/targetTimes_N3.json"

# frontendが描く動的気象レイヤーと1対1で対応させる。ここに無い要素は温まらない。
_LAYERS: tuple[_PrewarmLayer, ...] = (
    _PrewarmLayer("キキクル・土砂", "land", "png", _RISK_TARGET_TIMES),
    _PrewarmLayer("キキクル・大雨", "rain_mesh", "png", _RISK_TARGET_TIMES),
    _PrewarmLayer("キキクル・浸水", "inund", "png", _RISK_TARGET_TIMES),
    _PrewarmLayer("キキクル・洪水", "flood", "pbf", _RISK_TARGET_TIMES),
    _PrewarmLayer("線状降水帯予測マップ", "sjfcstmap", "png", _RASRF_TARGET_TIMES),
    _PrewarmLayer("雷ナウキャスト", "thns", "png", _NOWC_TARGET_TIMES),
    _PrewarmLayer("竜巻ナウキャスト", "trns", "png", _NOWC_TARGET_TIMES),
)


def _pick_current_entry(raw: list[dict], element_id: str | None) -> dict | None:
    """targetTimes.jsonのエントリ群から「現在」を表す1件を選ぶ。

    **`element_id`で先に絞ること。** targetTimes.jsonは、その要素のタイルが存在しない
    basetimeのエントリも持つ（`elements`配列に別の要素しか載っていないもの）。絞らずに
    最新basetimeを採ると、存在しないタイルを要求し続けて404になる。

    絞った候補のうち、直近の実況フレーム（validtime==basetime）でbasetime最大のものを返す。
    実況フレームが1件も無ければ、予測フレームを含む全候補から最大basetimeを返す。
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
    # nowc系のtargetTimes.jsonはmemberを持たないため、パスには固定値を置く。
    member = entry.get("member", "none") if layer.group != "nowc" else "none"
    paths = []
    for z in range(_MIN_ZOOM, layer.max_zoom + 1):
        # 配信元が実データを持たないズーム（zoomUseの偶奇に合わない段）は温めても空タイル
        # しか積まれない。要求されたときは親から補間するため（infrastructure/
        # jma_tile_interpolation.py）、親側さえ温まっていればよい。
        if not has_native_tile(layer.spec, z):
            continue
        for x, y in tiles_covering_bbox(_PREWARM_BBOX, z):
            paths.append(
                f"bosai/jmatile/data/{layer.group}/{basetime}/{member}/{validtime}/surf/"
                f"{layer.element_id}/{z}/{x}/{y}.{layer.extension}"
            )
    return paths


def _with_interpolated_zooms(
    element_id: str, zooms: dict[int, list[list[int]]]
) -> dict[int, list[list[int]]]:
    """実データの無いズーム（補間で埋める段）の在否を、親ズームの結果から補う。

    **インデックスは「載っていないタイルは空」とクライアントへ伝える**（frontend `jmaTileIndex.ts`）。
    プリウォームは実データのあるズームしか温めないため、補間で埋めるズームをそのまま
    載せずにおくと、クライアントはそこを一律「空」と見なして取りに来なくなり、
    補間（`jma_tile_interpolation.py`）が一度も動かない。

    補間結果が空になるのは親が空のときだけなので、**親に中身のあるタイルの4象限**を
    そのまま子ズームの中身ありとして載せればよい（追加の取得は発生しない）。
    """
    if not zooms:
        return zooms
    filled = dict(zooms)
    for zoom in range(min(zooms) + 1, effective_max_zoom(JMA_TILE_SPECS[element_id]) + 1):
        if source_zoom_for_interpolation(element_id, zoom) is None:
            continue
        parents = filled.get(zoom - 1)
        if not parents:
            continue
        filled[zoom] = [
            [x * 2 + dx, y * 2 + dy] for x, y in parents for dx in (0, 1) for dy in (0, 1)
        ]
    return filled


async def _store_index(
    layer_entries: dict[str, dict], present: dict[str, dict[int, list[list[int]]]]
) -> None:
    """在否インデックスを組み立てて保存する。

    クライアントは「自分が描こうとしている`basetime`と一致する要素だけ」インデックスを
    信用する必要があるため、要素ごとに`basetime`/`validtime`/`member`を持たせる
    （risk系・nowc系・rasrf系で更新タイミングが別々のため、1つの`basetime`では表せない）。
    `coverage`はインデックスが網羅している地理範囲で、**この外のタイルについては在否が
    不明なので従来どおり取得する**ことをクライアントへ伝える。
    """
    if not layer_entries:
        return
    payload = {
        "coverage": {
            "min_longitude": _PREWARM_BBOX.min_longitude,
            "min_latitude": _PREWARM_BBOX.min_latitude,
            "max_longitude": _PREWARM_BBOX.max_longitude,
            "max_latitude": _PREWARM_BBOX.max_latitude,
        },
        "elements": {
            element_id: {
                "basetime": entry.get("basetime"),
                "validtime": entry.get("validtime"),
                "member": entry.get("member", "none"),
                # ズームは文字列キー（JSONのオブジェクトキーは文字列のため、往復で型が
                # 変わらないようにここで揃える）。補間で埋めるズームは親から補う
                # （`_with_interpolated_zooms`参照）。
                "zooms": {
                    str(z): coords
                    for z, coords in sorted(
                        _with_interpolated_zooms(element_id, present.get(element_id, {})).items()
                    )
                },
            }
            for element_id, entry in layer_entries.items()
        },
    }
    await set_index(payload)


async def prewarm_jma_tiles(client: JmaTileClient) -> None:
    """対象範囲のタイルを列挙し、`JmaTileClient.get()`で取得する。

    Redisへの書き込みは`get()`の副作用で起きる。プリウォーム専用の書き込み経路は持たない
    ——持つと、通常の取得経路とキャッシュの形が分かれる。
    """
    started = time.monotonic()
    target_times_cache: dict[str, list[dict] | None] = {}
    all_paths: list[str] = []
    skipped_labels: list[str] = []
    layer_entries: dict[str, dict] = {}

    for layer in _LAYERS:
        if layer.target_times_path not in target_times_cache:
            raw = await client.get(layer.target_times_path)
            if raw is None or isinstance(raw, EmptyTile):
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
        entry = _pick_current_entry(raw_entries, layer.element_id)
        if entry is None:
            skipped_labels.append(layer.label)
            continue
        layer_entries[layer.element_id] = entry
        all_paths.extend(_tile_paths_for_layer(layer, entry))

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

    async def _fetch_one(path: str) -> None:
        nonlocal fetched, empty, errors, total_bytes
        async with semaphore:
            result = await client.get(path)
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
        coords = parse_tile_path(path)
        if coords is None or is_empty_tile(content, coords.ext):
            empty += 1
            return
        present.setdefault(coords.element, {}).setdefault(coords.z, []).append([coords.x, coords.y])

    await asyncio.gather(*(_fetch_one(path) for path in all_paths))
    await _store_index(layer_entries, present)

    elapsed_ms = round((time.monotonic() - started) * 1000)
    non_empty = sum(len(coords) for zooms in present.values() for coords in zooms.values())
    logger.info(
        "jma tile prewarm 完了 tiles=%d fetched=%d empty=%d errors=%d non_empty=%d total_bytes=%d elapsed_ms=%d",
        len(all_paths),
        fetched,
        empty,
        errors,
        non_empty,
        total_bytes,
        elapsed_ms,
    )
