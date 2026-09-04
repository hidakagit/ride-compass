"""タイル単位の静的Edge×公開軸スコア行列のプロセス内メモリキャッシュ（改善計画T536）。

`GraphService._get_or_build_tile_materials`が、z12タイル単位で`domain/evaluation.py:
build_static_edge_score_matrix`の結果（`StaticEdgeScoreMatrix`）をここへキャッシュする。
同一タイルへの2回目以降の探索リクエストは、Edgeごとのコスト計算（Pythonコールバック）を
一切行わずこの行列から配列演算でコストを合成できる（旧`infrastructure/axis_score_cache.py`
[Edge単位の辞書キャッシュ、T534。約1.3KB/Edge]を置き換える。本行列はEdgeあたり公開軸の
数×8バイト程度で収まる、T536実測はdocs/tasks/T536.md参照）。

**`infrastructure/graph_material_cache.py`（`EdgeMaterialBundle`等の材料そのもの）とは
意図的に別のキャッシュとして持つ**。軸スタジオでの軸定義編集（`AxisRegistryAdminService`
経由の`refresh_axis_definitions`）はこちらだけを`clear()`し、材料キャッシュ（DBアクセスを
伴う取得）は温存する——軸編集直後の最初のリクエストがDBへ再問い合わせせずに済み、
訪れたタイルぶんだけ静的スコア行列を再計算するだけで反映される設計（旧axis_score_cache.py
と同じ設計意図をタイル粒度へ引き継ぐ）。

**無効化方針（改善計画T538で変更）**: プロセス内メモリのLRU（タイル単位、
`graph_material_cache`と同じ`DEFAULT_MAX_TILES`）に加え、`infrastructure/
tile_persistent_cache.py`へも同じ内容をディスク永続化する（`graph_material_cache.py`と
同じ動機・設計、docs/tasks/T538.md）。無効化経路は2種類ある:

1. **PBF再取込・precomputeバッチ・構築ロジック変更**: `TILE_SCORE_MATRIX_CACHE_VERSION`の
   バージョン文字列を手動で上げる（`region_service.py: ROAD_SURFACE_TILE_VERSION`と
   同じ流儀。コメント参照）。
2. **軸定義編集（`refresh_axis_definitions`）**: バージョン文字列は据え置いたまま、
   `sync_disk_cache_with_axis_revision()`が軸定義の内容変化を検知した場合のみメモリ・
   ディスク両方のキャッシュを即座に削除する。軸編集はデプロイを伴わない実行時のAPI操作の
   ため、ファイル世代の手動更新では表現できないタイミングの無効化が要る（バージョン
   文字列を上げてしまうと、軸編集と無関係な他の全タイルのディスクキャッシュまで巻き添えで
   無効化されてしまう）。

`sync_disk_cache_with_axis_revision(revision)`は、`refresh_axis_definitions`が
`AxisDefinitionRepository.get_revision()`（`axis_registry_meta.revision`、軸定義の
追加・更新・削除のたびにDB側でインクリメントされる単調増加カウンタ）を渡して呼ぶ。
ディスクへ最後に永続化した時点のrevisionを予約タイル座標（`_REVISION_MARKER_TILE`、
実タイルのzoomと衝突しない）へ記録しておき、渡された`revision`と一致すればディスク
キャッシュを温存する（メモリだけクリアする——プロセス内で軸編集APIが呼ばれた直後の
反映のため、`refresh_axis_definitions`はアプリ起動時にも必ず1回呼ばれるが、起動直後は
メモリが元々空のため無害）。一致しなければ、従来どおり`clear()`でメモリ・ディスク両方を
削除し、新しいrevisionを記録し直す。**軸定義が実際には変わっていないアプリ起動のたびに
ディスクキャッシュを丸ごと再構築してしまう不具合の修正**（`refresh_axis_definitions`が
起動時にも軸編集時にも同じ経路を通ることの副作用で、T536導入時から存在していた。詳細は
docs/tasks/T546.md参照）。
"""

from collections import OrderedDict

from app.domain.evaluation import StaticEdgeScoreMatrix
from app.infrastructure import tile_persistent_cache

# graph_material_cache.pyのDEFAULT_MAX_TILESと同じ値（同じタイル粒度・同じ対象範囲
# [関東圏]を想定するため、上限も揃える）。
DEFAULT_MAX_TILES = 2_000

_cache: "OrderedDict[tuple[int, int, int], StaticEdgeScoreMatrix]" = OrderedDict()
_max_entries = DEFAULT_MAX_TILES

# ディスク永続化キャッシュ（tile_persistent_cache.py）のnamespace・バージョン
# （改善計画T538）。パスへ埋め込むことで対応しない世代のファイルを読まないようにする。
#
# 以下を実行したときはこの値を手動で上げること:
#   - PBF再取込（app/batch/import_pbf.py）
#   - 交差点分割の事前バッチ（app/batch/presplit_road_graph.py）
#   - `StaticEdgeScoreMatrix`が読む事前集計・派生データを更新するprecomputeバッチ
#     （precompute_edge_attribute_counts.py・precompute_elevation_attributes.py・
#     precompute_road_node_degrees.py・precompute_way_attribute_counts.py）
#   - `build_static_edge_score_matrix`自体の計算式変更（domain/evaluation.py）
#
# `app/batch/refresh_derived.py`（改善計画T281段階2、disaster-recovery.md参照）は
# PBF再取込を除く上記バッチ一式を1コマンドで実行するため、これを実行した場合も
# 同様に上げること。上げ忘れると、実行前に既にキャッシュ済みだったタイルはディスク
# 経由で古いまま復元され続け、未訪問タイルだけが新しい値になる（症状が局所的で
# 気づきにくい。改善計画T574、2026-09-04、`graph_material_cache.py`と同時に発現）。
#
# **軸定義（axis_definitionsテーブル）の追加・削除・shape_params調整はこの世代管理の
# 対象外**——軸スタジオでの編集は上記のバージョン更新（デプロイを伴う）ではなく、
# 下記`clear()`（`refresh_axis_definitions`経由の即時呼び出し）が担う。
# v1: 初版（改善計画T538）。
# v2: 改善計画T574。`app/batch/refresh_derived.py`が本番でこの版数を上げずに実行され、
#     DB側は更新済みなのにディスクキャッシュが古いまま参照され続ける不具合が発生したための
#     世代上げ（内容自体の変更は無い）。
# v3: 改善計画T575・T576。precompute_elevation_attributes.pyを本番で完走させた際の
#     世代上げ（内容自体の変更は無い）。
_CACHE_NAMESPACE = "score_matrix"
TILE_SCORE_MATRIX_CACHE_VERSION = "3"


def _remember(key: tuple[int, int, int], matrix: StaticEdgeScoreMatrix) -> None:
    """メモリLRUへ書き込み、上限超過分を退避する（`set()`・ディスクヒット時の
    再取り込みの両方から使う共通ロジック）。"""
    _cache[key] = matrix
    _cache.move_to_end(key)
    if len(_cache) > _max_entries:
        _cache.popitem(last=False)


def get(zoom: int, x: int, y: int, read_stats: dict[str, object] | None = None) -> StaticEdgeScoreMatrix | None:
    """改善計画T546: `read_stats`は`graph_material_cache.get_tile_materials`と同じ意味
    （"source"="memory"/"disk"＋ディスク経由時の"read_ms"/"unpickle_ms"/"bytes"）。"""
    key = (zoom, x, y)
    value = _cache.get(key)
    if value is not None:
        _cache.move_to_end(key)
        if read_stats is not None:
            read_stats["source"] = "memory"
        return value
    # 改善計画T538: メモリmissでもディスク永続化キャッシュを確認する（プロセス再起動
    # 直後や、LRU上限で立ち退いた直後がこの経路に該当する）。
    persisted: StaticEdgeScoreMatrix | None = tile_persistent_cache.get(
        _CACHE_NAMESPACE, TILE_SCORE_MATRIX_CACHE_VERSION, zoom, x, y, stats=read_stats
    )
    if persisted is None:
        return None
    if read_stats is not None:
        read_stats["source"] = "disk"
    _remember(key, persisted)
    return persisted


def set(zoom: int, x: int, y: int, matrix: StaticEdgeScoreMatrix) -> None:
    _remember((zoom, x, y), matrix)
    tile_persistent_cache.set(_CACHE_NAMESPACE, TILE_SCORE_MATRIX_CACHE_VERSION, zoom, x, y, matrix)


def clear() -> None:
    """テスト用、および軸定義の内容が実際に変わった場合
    （`sync_disk_cache_with_axis_revision`）に呼ぶ。

    改善計画T538: ディスク永続化キャッシュ（tile_persistent_cache）も同時に削除する。
    メモリだけクリアしてディスクを残すと、次回プロセス再起動時に軸編集前の古いスコア
    行列がディスクから復元されてしまう（軸編集はバージョン文字列の手動更新を伴わない
    実行時操作のため、即時削除で対応する。モジュールdocstring参照）。
    """
    _cache.clear()
    tile_persistent_cache.clear_namespace(_CACHE_NAMESPACE)


def size() -> int:  # テストの検証用（メモリLRUの件数のみ。ディスク側は対象外）
    return len(_cache)


# 改善計画T546フォローアップ: ディスクへ最後に永続化した時点のaxis_registry_meta.revisionを
# 記録する予約タイル座標。実タイルのzoomは常にROAD_GRAPH_TILE_ZOOM（12）のため、
# zoom=-1は衝突しない。`tile_score_matrix_cache.get/set`（StaticEdgeScoreMatrix専用）
# ではなく`tile_persistent_cache.get/set`を直接使う——このrevision値自体はメモリLRU
# （`_cache`、StaticEdgeScoreMatrix専用）へは乗せない。
_REVISION_MARKER_TILE = (-1, 0, 0)


def _read_persisted_axis_revision() -> int | None:
    zoom, x, y = _REVISION_MARKER_TILE
    return tile_persistent_cache.get(_CACHE_NAMESPACE, TILE_SCORE_MATRIX_CACHE_VERSION, zoom, x, y)


def _write_persisted_axis_revision(revision: int) -> None:
    zoom, x, y = _REVISION_MARKER_TILE
    tile_persistent_cache.set(_CACHE_NAMESPACE, TILE_SCORE_MATRIX_CACHE_VERSION, zoom, x, y, revision)


def sync_disk_cache_with_axis_revision(revision: int | None) -> None:
    """`refresh_axis_definitions`から呼ぶ（改善計画T546フォローアップ）。

    `revision`（`AxisDefinitionRepository.get_revision()`、軸定義の追加・更新・削除の
    たびにDB側でインクリメントされる単調増加カウンタ）が、ディスクへ最後に永続化した
    時点の記録と一致すれば、軸定義はディスクキャッシュ書き込み時点から変わっていないと
    判断してディスクキャッシュを温存する（メモリだけクリアする）。不一致
    （軸編集が実際にあった）または未記録（初回デプロイ）の場合は`clear()`でメモリ・
    ディスク両方を削除し、新しいrevisionを記録し直す。`revision`がNone
    （`axis_registry_meta`に行が無い等、想定外の状態）の場合は安全側に倒して常に`clear()`する
    （記録もしない——次回呼び出し時も同じ安全側判定になる）。

    アプリ起動時（`main.py`のlifespan）・軸編集API成功直後のいずれも`refresh_axis_
    definitions`から同じ経路で呼ばれるため、本関数が両者を区別する（起動時は大半の場合
    revisionが変わっておらずディスクキャッシュを温存でき、軸編集時のみ実際に無効化される）。
    """
    if revision is not None and _read_persisted_axis_revision() == revision:
        _cache.clear()
        return
    clear()
    if revision is not None:
        _write_persisted_axis_revision(revision)
