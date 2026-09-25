"""0次ハードフィルタ（Hard Constraint）。

スコア計算には一切登場させず、ルーティンググラフから除外する判定だけを担う。
フィルタごとに名前を付け、レシピ単位で個別に有効/無効を選べる。判定
（`compute_hard_filter_excluded`）はレジストリをループするため、フィルタを1つ
増やしても判定側は無変更で反映される。
"""

from typing import Mapping, NamedTuple

import numpy as np

from app.domain.material_sql import BICYCLE_NORMALIZED_SQL, HIGHWAY_SQL


class HighwayHardFilter(NamedTuple):
    #: 画面に出す名前。フィルタと同じ行に持つ——名前だけ別の表にすると、フィルタを
    #: 足したときに名前の無い行ができ、画面に内部名が出る。
    label: str
    highway_types: frozenset[str]


class TagHardFilter(NamedTuple):
    label: str
    #: 「該当するか」をSQLで表す式。
    predicate_sql: str


# highway種別で決まるフィルタ。ここへ1行足すだけで、名前の集合も判定式の列も画面の
# 名前も増える。
#
# 日本のtrunk（国道等の幹線道路）は法的には自転車通行可能な場合が多いが、ロードバイクの
# 周回ルートにとって「実質的に走りにくい・危険」という実務判断で除外対象に含める。
HARD_FILTER_HIGHWAY_TYPES: dict[str, HighwayHardFilter] = {
    "motorway": HighwayHardFilter("高速道路", frozenset({"motorway", "motorway_link"})),
    "trunk": HighwayHardFilter("幹線道路", frozenset({"trunk", "trunk_link"})),
}

# highwayでは決まらない、タグ由来のフィルタ。足すならここへ1エントリ書くだけでよい。
HARD_FILTER_TAG_PREDICATE_SQL: dict[str, TagHardFilter] = {
    "no_bicycle": TagHardFilter("自転車通行禁止", f"COALESCE({BICYCLE_NORMALIZED_SQL} = 'no', false)"),
}

#: フィルタ名→画面に出す名前。上の2つの宣言から導く。
HARD_FILTER_LABELS: dict[str, str] = {
    **{name: spec.label for name, spec in HARD_FILTER_HIGHWAY_TYPES.items()},
    **{name: spec.label for name, spec in HARD_FILTER_TAG_PREDICATE_SQL.items()},
}

# APIの`hard_filters`が受け付けるキー集合の正本。**別の場所で組み立て直さないこと**
# ——キー完全一致で検証するため、片方だけ増えた瞬間にすべてのルート生成が422になる。
HARD_FILTER_NAMES: frozenset[str] = frozenset({*HARD_FILTER_TAG_PREDICATE_SQL, *HARD_FILTER_HIGHWAY_TYPES})

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
    **{name: _highway_is_one_of_sql(spec.highway_types) for name, spec in HARD_FILTER_HIGHWAY_TYPES.items()},
    **{name: spec.predicate_sql for name, spec in HARD_FILTER_TAG_PREDICATE_SQL.items()},
}


def hard_filter_columns() -> tuple[str, ...]:
    """0次フィルタの列の並び。組み立てる側と読む側が別々に並べると意味がずれる。"""
    return tuple(sorted(HARD_FILTER_VALUE_SQL))


def compute_routable_nodes(
    edge_from: np.ndarray,
    edge_to: np.ndarray,
    hard_filter_excluded: np.ndarray,
    node_count: int,
) -> np.ndarray:
    """0次ハードフィルタで除外されなかった区間が1本以上あるノード（ノード番号順の真偽）。

    探索用グラフ（`domain/routing.py: LazyRoadGraph`）はHard Constraintをグラフ構造では
    なくコスト（`math.inf`）で表現するため、「実際に経路探索可能なNode」はここで別途
    求める必要がある。

    `hard_filter_excluded`は呼び出し元が探索コストを`inf`にするのに使うのと同じ配列を
    そのまま渡す想定で、`edge_from`・`edge_to`と**同じ行順・同じ長さ**。
    """
    kept = ~np.asarray(hard_filter_excluded, dtype=bool)
    routable = np.zeros(node_count, dtype=bool)
    routable[np.asarray(edge_from)[kept]] = True
    routable[np.asarray(edge_to)[kept]] = True
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

    `hard_filter_flags`は`HARD_FILTER_NAMES`のフィルタ名→該当フラグ配列で、**キー集合の
    完全一致を要求する**——欠けたフィルタは黙って無効になり、高速道路や`bicycle=no`の道が
    そのまま候補へ入る。`hard_filters`の名前も同じ理由で宣言に無いものを拒む
    （綴り間違いが「そのフィルタを切った」と区別できない）。フィルタを1つ増やしても
    この関数は変わらない。
    """
    active_hard_filters = hard_filters if hard_filters is not None else DEFAULT_HARD_FILTERS
    if set(hard_filter_flags) != HARD_FILTER_NAMES:
        raise ValueError(
            f"0次フィルタの列が宣言と違います 不足={sorted(HARD_FILTER_NAMES - set(hard_filter_flags))} "
            f"未知={sorted(set(hard_filter_flags) - HARD_FILTER_NAMES)}"
        )
    unknown = active_hard_filters - HARD_FILTER_NAMES
    if unknown:
        raise ValueError(f"宣言に無い0次フィルタ名: {sorted(unknown)}")
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
