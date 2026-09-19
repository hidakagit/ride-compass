"""0次ハードフィルタ（仕様書29章のHard Constraint）。

スコア計算には一切登場させず、ルーティンググラフから除外する判定だけを担う。
判定（`compute_hard_filter_excluded`）は`HARD_FILTER_HIGHWAY_TYPES`レジストリを
ループするため、フィルタを1つ増やしても判定側は無変更で反映される。
"""

from typing import Mapping

import numpy as np

from app.domain.graph import RoadGraphLike
from app.domain.material_sql import BICYCLE_NORMALIZED_SQL, HIGHWAY_SQL_FOR_EDGE


# 〇次: ハード制約（設計プロンプト「評価システムの層構造再設計」の〇次フィルタ。
# 仕様書29章のHard Constraintと同じ概念）。スコア計算には一切登場させず、
# ルーティンググラフから除外する。フィルタごとに名前を付け、レシピ単位で個別に
# 有効/無効を選択できる構造にしている。
#
# `motorway`は設計プロンプトが明示する高速道路（法的に自転車通行不可）。`trunk`は
# 設計プロンプトの〇次フィルタ表には無いが、日本のtrunk（国道等の幹線道路）は法的には
# 自転車通行可能な場合が多いにもかかわらず、本アプリの用途（ロードバイクの周回ルート
# 生成）にとって「実質的に走りにくい・危険」という実務判断で除外対象に含める。
# `no_bicycle`はOSMの`bicycle=no`タグ。
HARD_FILTER_HIGHWAY_TYPES: dict[str, frozenset[str]] = {
    "motorway": frozenset({"motorway", "motorway_link"}),
    "trunk": frozenset({"trunk", "trunk_link"}),
}

# 0次フィルタの名前の全体（APIの`hard_filters`が受け付けるキー集合の正本）。highway由来の
# フィルタは上のレジストリから導き、それ以外（タグ由来の`no_bicycle`）だけをここへ書く。
# **キー集合を別の場所で組み立て直さないこと**——片方だけ増えた瞬間にすべてのルート生成が
# 422になる（キー完全一致の検証のため）。
#
# highway種別のフィルタを増やすなら`HARD_FILTER_HIGHWAY_TYPES`へ1行足すだけで済む。
# タグ由来のフィルタを増やす場合はここへ名前を足すのに加え、`HARD_FILTER_TAG_PREDICATE_SQL`
# へ判定式を1本書く（`no_bicycle`が唯一の実例）。
# タグ由来のフィルタ。名前→「該当するか」をSQLで表す式。**名前をここ以外へ書かない**
# ——`HARD_FILTER_NAMES`も`HARD_FILTER_VALUE_SQL`もここから導く。
HARD_FILTER_TAG_PREDICATE_SQL: dict[str, str] = {
    "no_bicycle": f"COALESCE({BICYCLE_NORMALIZED_SQL} = 'no', false)",
}

HARD_FILTER_NAMES: frozenset[str] = frozenset(
    {*HARD_FILTER_TAG_PREDICATE_SQL, *HARD_FILTER_HIGHWAY_TYPES}
)

# 現時点の既定レシピは全フィルタを常時有効にする（is_edge_allowedの`hard_filters`
# 省略時のデフォルト値としても使う）。「受け付けるキー」と「既定でONのキー」は別の概念で、
# 今はたまたま一致している。
DEFAULT_HARD_FILTERS: frozenset[str] = HARD_FILTER_NAMES


def _highway_is_one_of_sql(highway_types: frozenset[str]) -> str:
    listed = ", ".join(f"'{value}'" for value in sorted(highway_types))
    return f"COALESCE({HIGHWAY_SQL_FOR_EDGE} IN ({listed}), false)"


# フィルタ名→「その区間が該当するか」をSQLで表す式。材料を読むクエリがこの名前のまま
# 列として受け取る（`infrastructure/road_graph_repository.py`）。
#
# **フィルタごとに専用の列を作らない**（設計原則 構造仕様8「拡張可能なレジストリは常に
# 1本道の追加点を持つ」）。highway由来のフィルタは上のレジストリから式を導くため、
# `HARD_FILTER_HIGHWAY_TYPES`へ1行足すだけで列も増える。タグ由来のフィルタだけを
# 個別に書く（`no_bicycle`が唯一の実例、`HARD_FILTER_NAMES`のコメントと同じ構造）。
#
# キー集合は`HARD_FILTER_NAMES`と同じものから導くため、ずれようがない
# （設計原則 構造仕様12「チェックの母集団は導出する。手で列挙しない」——
# 手書きの2本を突き合わせるテストを置くのではなく、1本から導く）。
HARD_FILTER_VALUE_SQL: dict[str, str] = {
    **{name: _highway_is_one_of_sql(types) for name, types in HARD_FILTER_HIGHWAY_TYPES.items()},
    **HARD_FILTER_TAG_PREDICATE_SQL,
}


def hard_filter_columns() -> tuple[str, ...]:
    """0次フィルタの列の並び。組み立てる側と読む側が別々に並べると意味がずれる。"""
    return tuple(sorted(HARD_FILTER_VALUE_SQL))




def compute_routable_node_ids(
    graph: RoadGraphLike,
    edge_ids: list[str],
    hard_filter_excluded: np.ndarray,
) -> set[str]:
    """0次ハードフィルタで除外されなかった（`hard_filter_excluded[i]`がFalse）Edgeが
    1本以上あるNode ID集合を返す。

    探索用グラフ（`domain/routing.py: LazyRoadGraph`）はHard Constraintをグラフ構造では
    なくコスト（`math.inf`）で表現するため、「実際に経路探索可能なNode」の判定は
    Hard Constraintだけを別途・軽量に評価して得る必要がある。

    この判定は`StaticEdgeScoreMatrix`の`hard_filter_flags`/`gradient_percent`列から
    `compute_hard_filter_excluded`が求める`excluded`配列と
    全く同じ内容（呼び出し元`road_graph_engine.py: _build_search_graph`がコスト配列を
    `inf`にする判定に使うのと同じ配列）である。呼び出し元がその配列をそのまま渡すことで、
    本関数は材料の表への依存を持たない（タイル材料
    キャッシュの復元コストとは独立になる）。`edge_ids`は`hard_filter_excluded`と同じ
    行順（`StaticEdgeScoreMatrix.edge_ids`）。
    """
    routable: set[str] = set()
    edges = graph.edges
    for edge_id, excluded in zip(edge_ids, hard_filter_excluded.tolist()):
        if excluded:
            continue
        edge = edges.get(edge_id)
        if edge is None:
            continue
        routable.add(edge.from_node_id)
        routable.add(edge.to_node_id)
    return routable


def compute_hard_filter_excluded(
    hard_filter_flags: Mapping[str, np.ndarray],
    gradient_percent: np.ndarray,
    hard_filters: frozenset[str] | None = None,
    max_average_grade_percent: float | None = None,
) -> np.ndarray:
    """静的スコア行列が持つ生フラグから、リクエスト時点の`hard_filters`/
    `max_average_grade_percent`を反映した0次フィルタ除外の真偽値配列を求める。
    省略時（既定None）は`DEFAULT_HARD_FILTERS`
    （全フィルタ常時有効）を使う。

    `hard_filter_flags`は`HARD_FILTER_NAMES`のフィルタ名→該当フラグ配列。
    フィルタを1つ増やしてもこの関数は変わらない。
    """
    active_hard_filters = hard_filters if hard_filters is not None else DEFAULT_HARD_FILTERS
    excluded = np.zeros(len(gradient_percent), dtype=bool)
    for filter_name, flags in hard_filter_flags.items():
        if filter_name in active_hard_filters:
            excluded |= flags
    # 勾配の〇次ハードフィルタ（NaNとの比較は常にFalseになるため、勾配不明のEdgeへは
    # 適用されない）。
    if max_average_grade_percent is not None:
        with np.errstate(invalid="ignore"):
            excluded |= np.abs(gradient_percent) > max_average_grade_percent
    return excluded
