import math

# 改善計画T423: 勾配（第2の具体例）。domain/wind.py: headwind_component_msと同型の「向きに依存する
# 動的材料」の純粋計算ロジック。docs/tasks/T423.md「確定済みの設計判断」1.で確定した
# cos連続補正を実装する。
#
# gradient_percentは道路自身の始点→終点方向を基準にした符号付き値（登り=正、下り=負、
# domain/route.py冒頭コメント参照）。ユーザーが指定した走行方位（travel_bearing_deg）が
# 道路自身の向き（road_bearing_deg）と一致するほど、その道路の勾配をそのまま受ける
# （cos(0)=1）。走行方位が道路の向きの真逆であれば、道路を逆走する想定になるため符号が
# 反転する（cos(180°)=-1、登り坂を逆に辿れば下り坂になる）。直角に近いほど「その道路は
# 指定方向とほぼ交差するだけで、指定方向にはほとんど進まない」とみなし影響を0へ近づける
# （cos(90°)=0）。風のwind_penaltyと同じ考え方の応用のため一貫性がある
# （二値反転案[±90°で符号切替]は境界で表示が急に切り替わる不自然さがあるため不採用、
# docs/tasks/T423.md参照）。
#
# road_bearing_deg（道路自身の向き）とtravel_bearing_deg（ユーザー指定の走行方位）を
# 入れ替えても結果は同じになる（cosは偶関数のため）。また、同じ道路の逆方向のroad_edges行
# （forward/backward、domain/graph.py参照）を使っても値は変わらない——逆方向は
# road_bearing_deg±180度・gradient_percentの符号反転の両方が起きるため、cos(±180度)=-1との
# 積で符号が2回反転し元に戻る（backend/app/infrastructure/road_graph_repository.py:
# get_way_gradient_inputs_in_tileがforward/backwardどちらの行を拾っても結果が一致する
# 理由、test_gradient.py: test_forward_and_backward_edge_agreeで検証）。


class GradientCalculator:
    """道路自身の勾配・向きと、ユーザーが指定した走行方位から、その方向へ走った場合の
    実効的な勾配（%）を計算する。

    正の値=登り、負の値=下り、0付近=道路をほぼ横切るだけで進行方向にはほとんど
    影響しない（走行方位が道路の向きとほぼ直角）。
    """

    @staticmethod
    def effective_gradient(gradient_percent: float, road_bearing_deg: float, travel_bearing_deg: float) -> float:
        diff = math.radians(road_bearing_deg - travel_bearing_deg)
        return gradient_percent * math.cos(diff)
