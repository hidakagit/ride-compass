"""タイル単位の静的Edge×公開軸スコア行列のキャッシュ（メモリLRU＋ディスク永続化）。

材料（`infrastructure/graph_material_cache.py`）とは別のキャッシュとして持つ。軸定義の
編集はこちらだけを`clear()`し、DBアクセスを伴う材料は温存するため、軸編集直後の最初の
リクエストは訪れたタイルぶんのスコア行列を再計算するだけで反映される。
"""


import logging

from cachetools import LRUCache

from app.domain.evaluation import (
    StaticEdgeScoreMatrix,
    route_facing_categorical_material_ids,
    route_facing_material_ids,
    route_facing_raw_axis_ids,
)
from app.domain.hard_filters import HARD_FILTER_NAMES
from app.infrastructure import cache_generation, tile_persistent_cache
from app.infrastructure.cache_identity import SCORE_MATRIX_REVISION, cache_identity
from app.infrastructure.graph_material_cache import TILE_MATERIALS_CACHE_VERSION

logger = logging.getLogger("ridecompass.tile_score_matrix_cache")

# graph_material_cache.pyのDEFAULT_MAX_TILESと同じ値（同じタイル粒度・同じ対象範囲
# [関東圏]を想定するため、上限も揃える）。
DEFAULT_MAX_TILES = 2_000

_cache: LRUCache = LRUCache(maxsize=DEFAULT_MAX_TILES)

# 鍵は材料側の世代との複合にする。この行列は材料から導出される派生物で、材料のedge_id集合が
# 変われば必ず無効になるため——単独の文字列にすると、材料世代だけを上げたときにスコア行列
# だけが古いまま残り、`graph`には在るが`score_matrix.edge_ids`には無いedge_idが生じる
# （`road_graph_engine.py`の`full_edge_row`引きがbbox単位でKeyErrorになり、ディスク
# キャッシュを手で消すまでそのbboxのルート生成が復旧しない）。
_CACHE_NAMESPACE = "score_matrix"
TILE_SCORE_MATRIX_CACHE_VERSION = cache_identity(
    SCORE_MATRIX_REVISION, TILE_MATERIALS_CACHE_VERSION, StaticEdgeScoreMatrix)


def _columns_match_current_predicates(matrix: StaticEdgeScoreMatrix) -> bool:
    """復元した行列の可変長の列が、いまの述語の出力と一致するか。

    `raw_axis_ids`/`material_ids`/`categorical_material_ids`/`hard_filter_flags`は
    `dataclasses.fields()`には
    現れない**中身で決まる列**で、鍵の署名（列名の並び）では捕まえられない。列を決める
    述語（`evaluation.py: has_route_facing_raw_value`・`MaterialSpec`の該当フィールド）はこのモジュールを
    触らずに変えられるため、版を上げ忘れると旧世代がそのまま復元される。列数が変われば
    `np.concatenate`がValueErrorで落ち、偶然一致すれば**別の軸の生値を表示する**。

    0次フィルタのキー集合（`HARD_FILTER_HIGHWAY_TYPES`）も同じ性質を持つ。宣言を1行足すだけで
    増やせる一方、旧世代が復元されると先頭タイルのキーで全タイルが揃うため、**利用者が除外した
    はずの道を通るルートが無警告で出る**（`.items()`で回すため例外にもならない）。
    """
    return (
        matrix.raw_axis_ids == route_facing_raw_axis_ids()
        and matrix.material_ids == route_facing_material_ids()
        and matrix.categorical_material_ids == route_facing_categorical_material_ids()
        and matrix.hard_filter_flags.keys() == HARD_FILTER_NAMES
    )


def get(zoom: int, x: int, y: int, read_stats: dict[str, object] | None = None) -> StaticEdgeScoreMatrix | None:
    """`read_stats`は`graph_material_cache.get_tile_materials`と同じ意味
    （"source"="memory"/"disk"＋ディスク経由時の"read_ms"）。"""
    key = (zoom, x, y)
    value = _cache.get(key)
    if value is not None:
        if read_stats is not None:
            read_stats["source"] = "memory"
        return value
    # メモリmissでもディスク永続化キャッシュを確認する（プロセス再起動
    # 直後や、LRU上限で立ち退いた直後がこの経路に該当する）。
    persisted: StaticEdgeScoreMatrix | None = tile_persistent_cache.get(
        _CACHE_NAMESPACE, TILE_SCORE_MATRIX_CACHE_VERSION, zoom, x, y, stats=read_stats
    )
    if persisted is None:
        return None
    if not _columns_match_current_predicates(persisted):
        # 版の上げ忘れをここで吸収する。ミス扱いにすれば呼び出し側が作り直すだけで済み、
        # 壊れた行列が探索へ入らない。
        logger.warning(
            "スコア行列の列構成が現在の述語と一致しないためミス扱いにします tile=%d/%d/%d", zoom, x, y
        )
        if read_stats is not None:
            read_stats["source"] = "stale_columns"
        return None
    if read_stats is not None:
        read_stats["source"] = "disk"
    _cache[key] = persisted
    return persisted


def set(zoom: int, x: int, y: int, matrix: StaticEdgeScoreMatrix) -> None:
    _cache[(zoom, x, y)] = matrix
    tile_persistent_cache.set(_CACHE_NAMESPACE, TILE_SCORE_MATRIX_CACHE_VERSION, zoom, x, y, matrix)


def prune_stale_disk_generations() -> int:
    """ディスク永続化キャッシュから、現行世代以外のスコア行列を削除する（解放バイト数を返す）。"""
    return tile_persistent_cache.prune_stale_generations(_CACHE_NAMESPACE, TILE_SCORE_MATRIX_CACHE_VERSION)


def clear() -> None:
    """メモリとディスクの両方を削除する。

    メモリだけクリアしてディスクを残すと、次回プロセス再起動時に軸編集前の古いスコア
    行列がディスクから復元されてしまう。
    """
    _cache.clear()
    tile_persistent_cache.clear_namespace(_CACHE_NAMESPACE)


def size() -> int:  # テストの検証用（メモリLRUの件数のみ。ディスク側は対象外）
    return len(_cache)


def sync_disk_cache_with_axis_revision(revision: int | None) -> None:
    """`refresh_axis_definitions`から軸定義の世代（`axis_registry_meta.revision`）を受ける。

    `refresh_axis_definitions`はアプリ起動時にも軸編集API成功直後にも同じ経路で呼ばれる。
    軸定義が変わっていなければディスクは温存し、メモリだけ空にする（起動のたびに
    ディスクキャッシュを丸ごと再構築しないため）。
    """
    if not cache_generation.sync_with_revision(
        _CACHE_NAMESPACE, TILE_SCORE_MATRIX_CACHE_VERSION, revision, clear
    ):
        _cache.clear()
