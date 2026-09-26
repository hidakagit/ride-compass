"""周回・目的地ルートの探索結果を運ぶ型。

探索の実装（`services/road_graph_engine.py`）と、候補を並べる戦略
（`services/route_generator.py`）の両方が読むため、どちらにも属さないここに置く。
"""

from dataclasses import dataclass
from typing import Any

from app.domain.geo import compass_label

#: 経由地・目的地を置いたルートのid。方位を持たないため、画面はタブに順位番号を付けず`direction_label`を出す。
WAYPOINTS_ROUTE_ID = "route-waypoints"


@dataclass
class LoopTurnaround:
    """`select_loop_turnarounds`が返す折返し点候補。

    `bearing`は起点から見た折返し点の方位で、表示ラベル用であり候補選定には使わない。
    `outbound_difficulty`は往路の距離加重平均difficulty（0-100、算出不能ならNone）。
    `data`は復路探索に使う中間データで、型は探索の実装が決める。
    """

    bearing: int
    outbound_difficulty: float | None
    data: Any


@dataclass
class TracedLoop:
    """`trace_loop`/`trace_loop_from_turnaround`の結果。距離フィルタに必要な情報と、
    `evaluate_loops`が完全な`RouteCandidate`を組み立てるための経路（探索用グラフの区間の番号列。
    戦略層は中身を読まない）を運ぶ。

    bearing=Noneは経由地(waypoints)指定ルートを表す。周回候補と異なり「向き」という
    概念を持たず、ユーザーが指定した訪問順序をそのまま保持する必要がある
    （`road_graph_engine.py: _build_best_candidate`の逆回り合成をスキップする判定に使う）。
    """

    bearing: int | None
    distance_km: float
    data: list[int]
    # 経路上の各Edgeがどのレグ（`_RoadGraphContext.legs`の添字。周回は0=往路・1=復路、
    # 経由地ルートはレグ番号）のコスト配列で探索されたか。区間表示が探索と同じ配列から
    # 値を読むために使う。既定値を持たせない——省略できると、復路まで往路の時刻で評価した
    # 区間表示が黙って出る（探索と表示が別の配列を読む）。
    leg_of_edge: list[int]


def candidate_identity(bearing: int | None) -> dict[str, str]:
    """方位から候補のid・方位ラベルを導出する。

    ここで振るidは一時的なもので、`generate_loops`が最終順位で振り直す——同じ方位に
    複数の候補が並びうるため、方位由来のidは一意にならない。
    """
    if bearing is None:
        return {"id": WAYPOINTS_ROUTE_ID, "direction_label": "経由地ルート"}
    return {"id": f"route-{bearing:03d}", "direction_label": compass_label(bearing)}
