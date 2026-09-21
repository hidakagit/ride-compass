"""0次ハードフィルタ（Hard Constraint）。

スコア計算には一切登場させず、ルーティンググラフから除外する判定だけを担う。
フィルタごとに名前を付け、レシピ単位で個別に有効/無効を選べる。判定
（`compute_hard_filter_excluded`）はレジストリをループするため、フィルタを1つ
増やしても判定側は無変更で反映される。
"""

from typing import Mapping

import numpy as np

from app.domain.graph import LeanRoadGraph
from app.domain.material_sql import BICYCLE_NORMALIZED_SQL, HIGHWAY_SQL


# highway種別で決まるフィルタ。名前→除外するhighwayの値。ここへ1行足すだけで、名前の
# 集合も判定式の列も増える。
#
# 日本のtrunk（国道等の幹線道路）は法的には自転車通行可能な場合が多いが、ロードバイクの
# 周回ルートにとって「実質的に走りにくい・危険」という実務判断で除外対象に含める。
HARD_FILTER_HIGHWAY_TYPES: dict[str, frozenset[str]] = {
    "motorway": frozenset({"motorway", "motorway_link"}),
    "trunk": frozenset({"trunk", "trunk_link"}),
}

# highwayでは決まらない、タグ由来のフィルタ。名前→「該当するか」をSQLで表す式。
# 足すならここへ1エントリ書くだけでよい。
HARD_FILTER_TAG_PREDICATE_SQL: dict[str, str] = {
    "no_bicycle": f"COALESCE({BICYCLE_NORMALIZED_SQL} = 'no', false)",
}

# APIの`hard_filters`が受け付けるキー集合の正本。**別の場所で組み立て直さないこと**
# ——キー完全一致で検証するため、片方だけ増えた瞬間にすべてのルート生成が422になる。
HARD_FILTER_NAMES: frozenset[str] = frozenset(
    {*HARD_FILTER_TAG_PREDICATE_SQL, *HARD_FILTER_HIGHWAY_TYPES}
)

# 既定レシピは全フィルタを常時有効にする。「受け付けるキー」と「既定でONのキー」は別の
# 概念で、たまたま一致している。
DEFAULT_HARD_FILTERS: frozenset[str] = HARD_FILTER_NAMES


def _highway_is_one_of_sql(highway_types: frozenset[str]) -> str:
    listed = ", ".join(f"'{value}'" for value in sorted(highway_types))
    return f"COALESCE({HIGHWAY_SQL} IN ({listed}), false)"


# フィルタ名→「その区間が該当するか」をSQLで表す式。材料を読むクエリがこの名前のまま
# 列として受け取る。**フィルタごとに専用の列を作らない**——上の2つのレジストリから導く
# ため、`HARD_FILTER_NAMES`とキー集合がずれようがない。
HARD_FILTER_VALUE_SQL: dict[str, str] = {
    **{name: _highway_is_one_of_sql(types) for name, types in HARD_FILTER_HIGHWAY_TYPES.items()},
    **HARD_FILTER_TAG_PREDICATE_SQL,
}


def hard_filter_columns() -> tuple[str, ...]:
    """0次フィルタの列の並び。組み立てる側と読む側が別々に並べると意味がずれる。"""
    return tuple(sorted(HARD_FILTER_VALUE_SQL))


def compute_routable_node_ids(
    graph: LeanRoadGraph,
    edge_ids: list[str],
    hard_filter_excluded: np.ndarray,
) -> set[str]:
    """0次ハードフィルタで除外されなかった（`hard_filter_excluded[i]`がFalse）Edgeが
    1本以上あるNode ID集合を返す。

    探索用グラフ（`domain/routing.py: LazyRoadGraph`）はHard Constraintをグラフ構造では
    なくコスト（`math.inf`）で表現するため、「実際に経路探索可能なNode」はここで別途
    求める必要がある。

    `hard_filter_excluded`は呼び出し元が探索コストを`inf`にするのに使うのと同じ配列を
    そのまま渡す想定で、本関数は材料の表を参照しない。`edge_ids`は
    `hard_filter_excluded`と同じ行順。
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
    `hard_filters`省略時は`DEFAULT_HARD_FILTERS`を使う。

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
