"""0次ハードフィルタ（仕様書29章のHard Constraint）。

スコア計算には一切登場させず、ルーティンググラフから除外する判定だけを担う。
スカラー版（`is_edge_allowed`、Edge1本）とベクトル版（`compute_hard_filter_excluded`、
配列）が同じ`HARD_FILTER_HIGHWAY_TYPES`レジストリをループするため、フィルタを
1つ増やしても両方の判定へ自動的に反映される。
"""

from typing import Mapping

import numpy as np

from app.domain.attributes import ElevationAttribute
from app.domain.graph import EdgeLike, RoadGraphLike
from app.domain.recipe import tag_value_is


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
# **フィルタを増やすときに書き換えるのはこの2箇所だけ**——キー集合を別の場所で組み立て
# 直すと、片方だけ増えた瞬間にすべてのルート生成が422になる（キー完全一致の検証のため）。
HARD_FILTER_NAMES: frozenset[str] = frozenset({"no_bicycle", *HARD_FILTER_HIGHWAY_TYPES})

# 現時点の既定レシピは全フィルタを常時有効にする（is_edge_allowedの`hard_filters`
# 省略時のデフォルト値としても使う）。「受け付けるキー」と「既定でONのキー」は別の概念で、
# 今はたまたま一致している。
DEFAULT_HARD_FILTERS: frozenset[str] = HARD_FILTER_NAMES


def is_edge_allowed(
    edge: EdgeLike,
    way_tags: dict[str, str] | None = None,
    hard_filters: frozenset[str] | None = None,
    elevation_attribute: ElevationAttribute | None = None,
    max_average_grade_percent: float | None = None,
) -> bool:
    """Hard Constraint（仕様書29章、〇次フィルタ）。highwayタグが`hard_filters`で有効な
    道路種別フィルタに該当するか、または`bicycle=no`（`no_bicycle`フィルタ）が明示されて
    いるかを判定する。

    `hard_filters`省略時は`DEFAULT_HARD_FILTERS`（現行の全フィルタ常時有効）を使う。
    レシピの`hard_filters`フィールドをそのまま渡せる形にしている。

    highwayタグが無い（不明）場合、way_tagsが無い（未取得）場合は除外しない。判断材料が
    無いEdgeまで一律除外すると経路探索対象が過度に狭まるため、不明な場合は許可し
    Soft Constraint側の評価に委ねる（carStress/bicycle_infra評価と同じway_tags=None時の
    扱い、compute_edge_costのdocstring参照）。

    `motor_vehicle=no`（自転車可の車両通行禁止）はここでは扱わない。自転車は法的に
    通行可能なため〇次のハード除外対象にはせず、二次軸（車ストレス）側の「該当区間は
    最善値へ固定」という特例として扱う（docs/architecture.md 7章参照）。

    `max_average_grade_percent`（T12 ADR原則5: 0次ハードフィルタのしきい値調整可能化）が
    指定され、かつ`elevation_attribute.average_grade`が取得済み（事前計算バッチ未実行の
    Edgeは値がNoneのため対象外＝許可のまま）の場合、その絶対値（登り・下りどちらの急勾配も
    対象）がしきい値を超えるEdgeを除外する。未指定（既定None）なら勾配による除外は
    行わない。
    """
    active_filters = hard_filters if hard_filters is not None else DEFAULT_HARD_FILTERS
    if edge.highway is not None:
        for filter_name, highway_types in HARD_FILTER_HIGHWAY_TYPES.items():
            if filter_name in active_filters and edge.highway in highway_types:
                return False
    if "no_bicycle" in active_filters and way_tags is not None and tag_value_is(way_tags, "bicycle", "no"):
        return False
    if (
        max_average_grade_percent is not None
        and elevation_attribute is not None
        and elevation_attribute.average_grade is not None
        and abs(elevation_attribute.average_grade) > max_average_grade_percent
    ):
        return False
    return True


def compute_routable_node_ids(
    graph: RoadGraphLike,
    edge_ids: list[str],
    hard_filter_excluded: np.ndarray,
) -> set[str]:
    """0次ハードフィルタで除外されなかった（`hard_filter_excluded[i]`がFalse）Edgeが
    1本以上あるNode ID集合を返す（設計の背景はdocs/tasks/T529.mdも参照）。

    探索用グラフ（`domain/routing.py: LazyRoadGraph`）はHard Constraintをグラフ構造では
    なくコスト（`math.inf`）で表現するため、「実際に経路探索可能なNode」の判定は
    Hard Constraintだけを別途・軽量に評価して得る必要がある。

    この判定は`StaticEdgeScoreMatrix`の`highway_filter_flags`/`no_bicycle`/
    `gradient_percent`列から`compute_hard_filter_excluded`が求める`excluded`配列と
    全く同じ内容（呼び出し元`road_graph_engine.py: _build_search_graph`がコスト配列を
    `inf`にする判定に使うのと同じ配列）である。呼び出し元がその配列をそのまま渡すことで、
    本関数は`EdgeMaterialTable`/`EdgeMaterialBundle`辞書への依存を持たない（タイル材料
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
    highway_filter_flags: Mapping[str, np.ndarray],
    no_bicycle: np.ndarray,
    gradient_percent: np.ndarray,
    hard_filters: frozenset[str] | None = None,
    max_average_grade_percent: float | None = None,
) -> np.ndarray:
    """`_evaluate_axes_bulk`が返す生フラグから、リクエスト時点の`hard_filters`/
    `max_average_grade_percent`を反映した0次フィルタ除外の真偽値配列を求める
    （`is_edge_allowed`のベクトル版）。省略時（既定None）は`DEFAULT_HARD_FILTERS`
    （全フィルタ常時有効）を使う。

    `highway_filter_flags`は`HARD_FILTER_HIGHWAY_TYPES`のフィルタ名→該当フラグ配列
    （スカラー版`is_edge_allowed`が同じレジストリをそのままループするのと対称）。
    フィルタを1つ増やしてもこの関数は変わらない。
    """
    active_hard_filters = hard_filters if hard_filters is not None else DEFAULT_HARD_FILTERS
    excluded = np.zeros(len(no_bicycle), dtype=bool)
    for filter_name, flags in highway_filter_flags.items():
        if filter_name in active_hard_filters:
            excluded |= flags
    if "no_bicycle" in active_hard_filters:
        excluded |= no_bicycle
    # 勾配の〇次ハードフィルタ（NaNとの比較は常にFalseになるため、勾配不明のEdgeへは
    # 適用されない）。
    if max_average_grade_percent is not None:
        with np.errstate(invalid="ignore"):
            excluded |= np.abs(gradient_percent) > max_average_grade_percent
    return excluded
