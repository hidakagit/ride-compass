"""Road Graph探索用素材のキャッシュ（メモリLRU＋ディスク永続化）。

`GraphService.get_search_materials_for_bbox`が、z12タイル単位（`domain/region.py:
ROAD_GRAPH_TILE_ZOOM`）でトポロジと材料をここへキャッシュする。ディスクへも持つのは、
デプロイでプロセスが再起動してもDB読み出し（冷パスは29〜45秒規模）を避けるため。
"""


from cachetools import LRUCache

from app.domain.attributes import EdgeMaterialArrays, SearchMaterials
from app.domain.graph import LeanEdge, LeanNode
from app.infrastructure import cache_generation, tile_persistent_cache
from app.infrastructure.cache_identity import shape_digest


# 1タイルあたりの素材（Edge数百〜数千件分の辞書群）を想定した上限。関東圏（z12タイル
# 数百枚規模）を余裕を持ってカバーできる値。
DEFAULT_MAX_TILES = 2_000

_CACHE_NAMESPACE = "materials"
# `LeanNode`/`LeanEdge`も署名へ入れる。キャッシュ値（`SearchMaterials`）は材料だけでなく
# グラフのトポロジも抱えており、ノード・Edgeの列を足すと古いキャッシュには新しい列が無い。
# `EdgeMaterialArrays`だけを署名すると、鍵が動かないまま足した列が既定値のまま返り続ける。
TILE_MATERIALS_CACHE_VERSION = shape_digest(EdgeMaterialArrays, LeanNode, LeanEdge)


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
    """
    return cache_generation.sync_with_revision(
        _CACHE_NAMESPACE, TILE_MATERIALS_CACHE_VERSION, revision, clear
    )


def prune_stale_disk_generations() -> int:
    """ディスク永続化キャッシュから、現行世代以外のタイル材料を削除する（解放バイト数を返す）。"""
    return tile_persistent_cache.prune_stale_generations(_CACHE_NAMESPACE, TILE_MATERIALS_CACHE_VERSION)


def get_accident_years_covered() -> int | None:
    return _accident_years_covered_cache


def set_accident_years_covered(value: int) -> None:
    global _accident_years_covered_cache
    _accident_years_covered_cache = value


def clear() -> None:
    """メモリとディスクの両方を消す。

    **本番でも呼ばれる**——DBの派生データ世代が変わったときに
    `sync_disk_cache_with_derived_data_revision`が`clear`として渡す（材料はテーブルの
    中身そのものなので、作り直されたら捨てるしかない）。
    """
    _tile_materials_cache.clear()
    global _accident_years_covered_cache
    _accident_years_covered_cache = None
    tile_persistent_cache.clear_namespace(_CACHE_NAMESPACE)
