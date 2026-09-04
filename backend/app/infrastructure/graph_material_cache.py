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
# 以下を実行したときはこの値を手動で上げること（`app/batch/refresh_derived.py`
# ［改善計画T281段階2、disaster-recovery.md参照］はPBF再取込を除く下記バッチ一式を
# 1コマンドで実行するため、これを実行した場合も同様に上げること）:
#   - PBF再取込（app/batch/import_pbf.py）
#   - 交差点分割の事前バッチ（app/batch/presplit_road_graph.py）
#   - SearchMaterialsが読む事前集計・派生データを更新するprecomputeバッチ
#     （precompute_edge_attribute_counts.py・precompute_elevation_attributes.py・
#     precompute_road_node_degrees.py・precompute_way_attribute_counts.py）
#   - `EdgeMaterialBundle`・`SearchMaterials`自体の構築ロジック変更
#     （domain/attributes.py・services/graph_service.py: _get_or_build_tile_materials）
#
# 上げないと、バッチ実行前に既にメモリ・ディスクへキャッシュ済みだったタイルは、
# プロセス再起動をまたいでも（ディスク経由で）古いまま復元され続ける。バッチ実行
# より前に一度もアクセスされたことのないタイルだけが、バッチ後の初回アクセス時に
# DBから新しい値を読み新規キャッシュされる——「一部のタイルだけ更新が反映されている
# ように見える」形で症状が局所的になり気づきにくい（改善計画T574、2026-09-04、
# 実際にこの状態で本番の欠損比率計測が変化しない不具合として発現した）。
# v1: 初版（改善計画T538）。
# v2: `SearchMaterials.materials`をEdgeMaterialBundle辞書から列指向の`EdgeMaterialTable`へ
#     変更（改善計画T546、T538再検討案C1）。保存形式が変わるため世代を上げる
#     （`TILE_SCORE_MATRIX_CACHE_VERSION`は`StaticEdgeScoreMatrix`自体は無変更のため据え置き）。
# v3: 改善計画T574。`app/batch/refresh_derived.py`（precompute_edge_attribute_counts等の
#     一括実行）が本番でこの版数を上げずに実行され、DB側は更新済みなのにディスク
#     キャッシュが古いまま参照され続ける不具合が発生したための世代上げ（内容自体の変更は
#     無い）。
# v4: 改善計画T575・T576。precompute_elevation_attributes.pyを本番で完走させた際の
#     世代上げ（内容自体の変更は無い）。
_CACHE_NAMESPACE = "materials"
TILE_MATERIALS_CACHE_VERSION = "4"


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


def get_tile_materials(
    zoom: int, x: int, y: int, read_stats: dict[str, object] | None = None
) -> SearchMaterials | None:
    """改善計画T546: `read_stats`を渡すと、"source"（memory/disk）と、ディスク経由時は
    追加で"read_ms"/"unpickle_ms"/"bytes"（`tile_persistent_cache.get`参照）を書き込む
    （`graph_service.py`がリクエスト単位の1行INFOサマリへ集約する、対応方針項目6）。
    """
    cached = _tile_materials_cache.get((zoom, x, y))
    if cached is not None:
        if read_stats is not None:
            read_stats["source"] = "memory"
        return cached
    # 改善計画T538: メモリmissでもディスク永続化キャッシュを確認する（プロセス再起動
    # 直後や、LRU上限で立ち退いた直後がこの経路に該当する）。ディスクヒット時はメモリ
    # LRUへも載せ直し、同一プロセス内の以後のアクセスは再度ディスクI/Oを経由しない。
    persisted: SearchMaterials | None = tile_persistent_cache.get(
        _CACHE_NAMESPACE, TILE_MATERIALS_CACHE_VERSION, zoom, x, y, stats=read_stats
    )
    if persisted is None:
        return None
    if read_stats is not None:
        read_stats["source"] = "disk"
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
