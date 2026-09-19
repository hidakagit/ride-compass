"""Road Graph探索用素材のプロセス内メモリキャッシュ。

`GraphService.get_search_materials_for_bbox`が、z12タイル単位（`domain/region.py:
ROAD_GRAPH_TILE_ZOOM`）でトポロジ・材料（surface/edge_attribute_counts/way_tags/
elevation_attributes/designated_edge_ids）をここへキャッシュする。同一エリアへの
2回目以降のリクエストは、該当タイルがキャッシュ済みならDBへ一切アクセスしない。

**無効化方針**: プロセス内メモリのLRUに加え、
`infrastructure/tile_persistent_cache.py`（`TILE_MATERIALS_CACHE_VERSION`参照）へも
同じ内容をディスク永続化する。デプロイのたびにプロセスが再起動されても、ディスク
キャッシュが残っていればDB読み出しを経由せず復元できる（冷パスは29〜45秒規模かかる
ため、これを避ける）。ディスク側の無効化は2つの軸で行う——列構成の変化は
`TILE_MATERIALS_CACHE_VERSION`（`infrastructure/cache_identity.py`参照）が鍵を変えて、
中身の作り直しは`sync_disk_cache_with_derived_data_revision`がDBの世代と突き合わせて捨てる。

LRUで上限件数を設ける（無制限にすると全国規模まで対象が広がった場合にメモリを
際限なく消費するため）。1タイル（z12、日本付近で1辺約10km）あたりの素材サイズは
road_edges/road_nodesの密度次第だが、対象が関東圏に留まる現状の運用規模では
実害が無いと判断（他のプロセス内メモリキャッシュ[elevation_client.py]と
同じ割り切り）。将来対象範囲が全国規模まで広がる場合は上限値の見直しを検討する
（ディスク側はLRU退避を持たず世代切り替えのみで無効化する設計のため、対象範囲が
広がった場合はディスク容量側で別途検討する）。
"""


from cachetools import LRUCache

from app.domain.attributes import EdgeMaterialTable, SearchMaterials
from app.domain.graph import LeanEdge, LeanNode
from app.infrastructure import cache_generation, tile_persistent_cache
from app.infrastructure.cache_identity import shape_digest


# 1タイルあたりの素材（Edge数百〜数千件分の辞書群）を想定した上限。関東圏（z12タイル
# 数百枚規模）を余裕を持ってカバーできる値。
DEFAULT_MAX_TILES = 2_000

# ディスク永続化キャッシュ（tile_persistent_cache.py）のnamespace・バージョン。
# パスへ埋め込むことで対応しない世代のファイルを読まないようにする。**`EdgeMaterialTable`の
# 列構成だけから決まる**——列を足す・消す・並べ替えると鍵が自動で変わる。
# 中身の作り直し（バッチ再実行）はこの鍵ではなく`sync_disk_cache_with_derived_data_revision`
# が扱う。デプロイを伴わない操作のため、鍵を変える方式では表せない。
_CACHE_NAMESPACE = "materials"
# `LeanNode`/`LeanEdge`も署名へ入れる。キャッシュ値（`SearchMaterials`）は材料だけでなく
# グラフのトポロジも抱えており、ノード・Edgeの列を足すと古いキャッシュには新しい列が無い。
# `EdgeMaterialTable`だけを署名すると、鍵が動かないまま足した列が既定値のまま返り続ける。
TILE_MATERIALS_CACHE_VERSION = shape_digest(EdgeMaterialTable, LeanNode, LeanEdge)


_tile_materials_cache: LRUCache = LRUCache(maxsize=DEFAULT_MAX_TILES)
# accident_years_coveredはbboxに依存しないグローバルな値（事故データの収録年数）のため、
# タイル単位ではなく単一値としてキャッシュする。
_accident_years_covered_cache: int | None = None


def get_tile_materials(
    zoom: int, x: int, y: int, read_stats: dict[str, object] | None = None
) -> SearchMaterials | None:
    """`read_stats`を渡すと、"source"（memory/disk）と、ディスク経由時は
    追加で"read_ms"（`tile_persistent_cache.get`参照）を書き込む
    （`graph_service.py`がリクエスト単位の1行INFOサマリへ集約する）。
    """
    cached = _tile_materials_cache.get((zoom, x, y))
    if cached is not None:
        if read_stats is not None:
            read_stats["source"] = "memory"
        return cached
    # メモリmissでもディスク永続化キャッシュを確認する（プロセス再起動
    # 直後や、LRU上限で立ち退いた直後がこの経路に該当する）。ディスクヒット時はメモリ
    # LRUへも載せ直し、同一プロセス内の以後のアクセスは再度ディスクI/Oを経由しない。
    persisted: SearchMaterials | None = tile_persistent_cache.get(
        _CACHE_NAMESPACE, TILE_MATERIALS_CACHE_VERSION, zoom, x, y, stats=read_stats
    )
    if persisted is None:
        return None
    if read_stats is not None:
        read_stats["source"] = "disk"
    _tile_materials_cache[(zoom, x, y)] = persisted
    return persisted


def set_tile_materials(zoom: int, x: int, y: int, materials: SearchMaterials) -> None:
    _tile_materials_cache[(zoom, x, y)] = materials
    tile_persistent_cache.set(_CACHE_NAMESPACE, TILE_MATERIALS_CACHE_VERSION, zoom, x, y, materials)


def sync_disk_cache_with_derived_data_revision(revision: int | None) -> bool:
    """DBの派生データ世代とディスクキャッシュの中身を突き合わせ、食い違っていれば消す。
    消したときTrueを返す（呼び出し側が、材料から作られる他のキャッシュも消すため）。

    判断そのものは`cache_generation.sync_with_revision`が持つ——軸定義の編集
    （`tile_score_matrix_cache`）と同じ比較で、対象と捨てるものだけが違う。
    """
    return cache_generation.sync_with_revision(
        _CACHE_NAMESPACE, TILE_MATERIALS_CACHE_VERSION, revision, clear
    )


def read_persisted_revision() -> int | None:
    return cache_generation.read_persisted_revision(_CACHE_NAMESPACE, TILE_MATERIALS_CACHE_VERSION)


def prune_stale_disk_generations() -> int:
    """ディスク永続化キャッシュから、現行世代以外のタイル材料を削除する（解放バイト数を返す）。"""
    return tile_persistent_cache.prune_stale_generations(_CACHE_NAMESPACE, TILE_MATERIALS_CACHE_VERSION)


def get_accident_years_covered() -> int | None:
    return _accident_years_covered_cache


def set_accident_years_covered(value: int) -> None:
    global _accident_years_covered_cache
    _accident_years_covered_cache = value


def clear() -> None:
    """キャッシュを全消去する。

    **本番でも呼ばれる**——DBの派生データ世代が変わったときに
    `sync_disk_cache_with_derived_data_revision`が`clear`として渡す（材料はテーブルの
    中身そのものなので、作り直されたら捨てるしかない）。テストの後始末にも使う。

    メモリLRUだけでなくディスク永続化キャッシュ（tile_persistent_cache）も
    削除する。片方だけ残すとテスト間の汚染経路が増える（ディスクが前のテストの内容を
    残したまま次のテストがメモリmiss→ディスクhitしてしまう）。
    """
    _tile_materials_cache.clear()
    global _accident_years_covered_cache
    _accident_years_covered_cache = None
    tile_persistent_cache.clear_namespace(_CACHE_NAMESPACE)
