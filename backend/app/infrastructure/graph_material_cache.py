"""Road Graph探索用素材のプロセス内メモリキャッシュ（改善計画T219、T12 ADR Stage 1）。

`GraphService.get_search_materials_for_bbox`が、z12タイル単位（`domain/region.py:
ROAD_GRAPH_TILE_ZOOM`）でトポロジ・材料（surface/edge_attribute_counts/way_tags/
elevation_attributes/designated_edge_ids）をここへキャッシュする。同一エリアへの
2回目以降のリクエストは、該当タイルがキャッシュ済みならDBへ一切アクセスしない。

**無効化方針: バージョン管理は行わず、プロセス寿命でのみキャッシュする**
（ユーザー承認済み、2026-08-23）。PBF再取込・各precomputeバッチ（edge_attribute_counts/
elevation_attributes/road_node_degrees等）はいずれも手動・低頻度のバッチ操作であり、
本番はデプロイのたびにプロセスが再起動される前提を踏まえた単純化（T10のDEMタイル
キャッシュ、`infrastructure/tile_cache.py`と同じ考え方）。運用中にバッチを再実行して
キャッシュ済みタイルの元データを更新した場合、対象タイルの結果はプロセス再起動まで
古いまま返る点に注意（再起動すれば解消する）。

LRUで上限件数を設ける（無制限にすると全国規模まで対象が広がった場合にメモリを
際限なく消費するため）。1タイル（z12、日本付近で1辺約10km）あたりの素材サイズは
road_edges/road_nodesの密度次第だが、対象が関東圏に留まる現状の運用規模では
実害が無いと判断（他のプロセス内メモリキャッシュ[weather_client.py・elevation_client.py]と
同じ割り切り）。将来対象範囲が全国規模まで広がる場合は上限値の見直しを検討する。
"""

from collections import OrderedDict
from typing import Generic, TypeVar

from app.domain.attributes import SearchMaterials

_T = TypeVar("_T")

# 1タイルあたりの素材（Edge数百〜数千件分の辞書群）を想定した上限。関東圏（z12タイル
# 数百枚規模）を余裕を持ってカバーできる値。
DEFAULT_MAX_TILES = 2_000


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
    return _tile_materials_cache.get((zoom, x, y))


def set_tile_materials(zoom: int, x: int, y: int, materials: SearchMaterials) -> None:
    _tile_materials_cache.set((zoom, x, y), materials)


def get_accident_years_covered() -> int | None:
    return _accident_years_covered_cache


def set_accident_years_covered(value: int) -> None:
    global _accident_years_covered_cache
    _accident_years_covered_cache = value


def clear() -> None:
    """テスト用。キャッシュを全消去する（本番コードパスからは呼ばない）。"""
    _tile_materials_cache.clear()
    global _accident_years_covered_cache
    _accident_years_covered_cache = None
