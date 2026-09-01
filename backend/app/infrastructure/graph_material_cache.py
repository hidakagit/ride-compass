"""Road Graph探索用素材のプロセス内メモリキャッシュ（改善計画T219、T12 ADR Stage 1）。

`GraphService.get_search_materials_for_bbox`が、z12タイル単位（`domain/region.py:
ROAD_GRAPH_TILE_ZOOM`）でトポロジ・材料（surface/edge_attribute_counts/way_tags/
elevation_attributes/designated_edge_ids）をここへキャッシュする。同一エリアへの
2回目以降のリクエストは、該当タイルがキャッシュ済みならDBへ一切アクセスしない。

**無効化方針（改善計画T538で変更）**: プロセス内メモリのLRUに加え、
`infrastructure/tile_persistent_cache.py`（`TILE_MATERIALS_CACHE_VERSION`参照）へも
同じ内容をディスク永続化する。デプロイのたびにプロセスが再起動されても、ディスク
キャッシュが残っていればDB読み出しを経由せず復元できる（本番実測29〜45秒だった冷パスを
避ける、docs/tasks/T538.md）。ディスク側の無効化はバージョン文字列を手動で上げる方式
（`region_service.py: ROAD_SURFACE_TILE_VERSION`と同じ流儀、`TILE_MATERIALS_CACHE_VERSION`
のコメント参照）。

LRUで上限件数を設ける（無制限にすると全国規模まで対象が広がった場合にメモリを
際限なく消費するため）。1タイル（z12、日本付近で1辺約10km）あたりの素材サイズは
road_edges/road_nodesの密度次第だが、対象が関東圏に留まる現状の運用規模では
実害が無いと判断（他のプロセス内メモリキャッシュ[weather_client.py・elevation_client.py]と
同じ割り切り）。将来対象範囲が全国規模まで広がる場合は上限値の見直しを検討する
（ディスク側はLRU退避を持たず世代切り替えのみで無効化する設計のため、対象範囲が
広がった場合はディスク容量側で別途検討する）。
"""

from collections import OrderedDict
from typing import Generic, TypeVar

from app.domain.attributes import SearchMaterials
from app.infrastructure import tile_persistent_cache

_T = TypeVar("_T")

# 1タイルあたりの素材（Edge数百〜数千件分の辞書群）を想定した上限。関東圏（z12タイル
# 数百枚規模）を余裕を持ってカバーできる値。
DEFAULT_MAX_TILES = 2_000

# ディスク永続化キャッシュ（tile_persistent_cache.py）のnamespace・バージョン
# （改善計画T538）。パスへ埋め込むことで対応しない世代のファイルを読まないようにする
# （region_service.py: ROAD_SURFACE_TILE_VERSIONと同じ流儀）。
#
# 以下を実行したときはこの値を手動で上げること:
#   - PBF再取込（app/batch/import_pbf.py）
#   - 交差点分割の事前バッチ（app/batch/presplit_road_graph.py）
#   - SearchMaterialsが読む事前集計・派生データを更新するprecomputeバッチ
#     （precompute_edge_attribute_counts.py・precompute_elevation_attributes.py・
#     precompute_road_node_degrees.py・precompute_way_attribute_counts.py）
#   - `EdgeMaterialBundle`・`SearchMaterials`自体の構築ロジック変更
#     （domain/attributes.py・services/graph_service.py: _get_or_build_tile_materials）
#
# 上げないと、実行前にディスクへ書き込まれた古いタイル材料が、次回デプロイでプロセスが
# 再起動した瞬間から復元されてしまう（バッチ実行後もメモリキャッシュはプロセス寿命内は
# 温存されるため、バッチ直後は気づきにくい点に注意）。
# v1: 初版（改善計画T538）。
_CACHE_NAMESPACE = "materials"
TILE_MATERIALS_CACHE_VERSION = "1"


class _LRUCache(Generic[_T]):
    def __init__(self, max_size: int):
        self._max_size = max_size
        self._data: OrderedDict[tuple[int, int, int], _T] = OrderedDict()

    def get(self, key: tuple[int, int, int]) -> _T | None:
        value = self._data.get(key)
        if value is not None:
            self._data.move_to_end(key)
        return value

    def set(self, key: tuple[int, int, int], value: _T) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        self._data.clear()


_tile_materials_cache: _LRUCache[SearchMaterials] = _LRUCache(DEFAULT_MAX_TILES)
# accident_years_coveredはbboxに依存しないグローバルな値（事故データの収録年数）のため、
# タイル単位ではなく単一値としてキャッシュする。
_accident_years_covered_cache: int | None = None


def get_tile_materials(zoom: int, x: int, y: int) -> SearchMaterials | None:
    cached = _tile_materials_cache.get((zoom, x, y))
    if cached is not None:
        return cached
    # 改善計画T538: メモリmissでもディスク永続化キャッシュを確認する（プロセス再起動
    # 直後や、LRU上限で立ち退いた直後がこの経路に該当する）。ディスクヒット時はメモリ
    # LRUへも載せ直し、同一プロセス内の以後のアクセスは再度ディスクI/Oを経由しない。
    persisted: SearchMaterials | None = tile_persistent_cache.get(
        _CACHE_NAMESPACE, TILE_MATERIALS_CACHE_VERSION, zoom, x, y
    )
    if persisted is None:
        return None
    _tile_materials_cache.set((zoom, x, y), persisted)
    return persisted


def set_tile_materials(zoom: int, x: int, y: int, materials: SearchMaterials) -> None:
    _tile_materials_cache.set((zoom, x, y), materials)
    tile_persistent_cache.set(_CACHE_NAMESPACE, TILE_MATERIALS_CACHE_VERSION, zoom, x, y, materials)


def get_accident_years_covered() -> int | None:
    return _accident_years_covered_cache


def set_accident_years_covered(value: int) -> None:
    global _accident_years_covered_cache
    _accident_years_covered_cache = value


def clear() -> None:
    """テスト用。キャッシュを全消去する（本番コードパスからは呼ばない）。

    改善計画T538: メモリLRUだけでなくディスク永続化キャッシュ（tile_persistent_cache）も
    削除する。片方だけ残すとテスト間の汚染経路が増える（ディスクが前のテストの内容を
    残したまま次のテストがメモリmiss→ディスクhitしてしまう）。
    """
    _tile_materials_cache.clear()
    global _accident_years_covered_cache
    _accident_years_covered_cache = None
    tile_persistent_cache.clear_namespace(_CACHE_NAMESPACE)
