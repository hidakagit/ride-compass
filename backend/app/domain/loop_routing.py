"""周回・目的地ルートの探索結果を運ぶ型。

探索の実装（`services/road_graph_engine.py`）と、候補を並べる戦略
（`services/route_generator.py`）の両方が読むため、どちらにも属さないここに置く。
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class LoopTurnaround:
    """`select_loop_turnarounds`が返す折返し点候補。

    `bearing`は起点から見た折返し点の方位で、表示ラベル用であり候補選定には使わない。
    `data`は復路探索に使う中間データで、型は探索の実装が決める。
    """

    bearing: int
    data: Any


@dataclass
class TracedLoop:
    """`trace_loop_from_turnaround`/`select_via_nodes`等、探索が確定した1本の経路。距離フィルタに必要な情報と、
    `evaluate_loops`が`RouteDraft`を組み立てるための経路（探索用グラフの区間の番号列。
    戦略層は中身を読まない）を運ぶ。
    """

    # 出発地から見た中継点の方位。名前（`direction_label`）にだけ使い、方位を持たない経路（目的地で終わる・
    # 距離なしの代わりの道）はNone。
    bearing: int | None
    distance_km: float
    data: list[int]
    # 経路上の各Edgeがどのレグ（`_RoadGraphContext.legs`の添字。前段の区間ごとのレグのあとに往路・帰り）の
    # コスト配列で探索されたか。区間表示が探索と同じ配列から値を読むために使う。既定値を持たせない——省略できると、
    # 帰りまで往路の時刻で評価した区間表示が黙って出る（探索と表示が別の配列を読む）。
    leg_of_edge: list[int]
    # 逆に回った経路も作って比べてよいか。出発地へ戻り、逆に回っても置いた経由地を置いた順に通るとき（経由地が
    # 1つ以下）だけ真（`road_graph_engine.py: _build_best_candidate`）。置いた順は利用者の意図なので崩さない。
    reversible: bool

