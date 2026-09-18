import math

# domain/wind.py: wind_drag_ratioと同型の「向きに依存する動的材料」の純粋計算ロジック。
#
# gradient_percentは道路自身の始点→終点方向を基準にした符号付き値（登り=正、下り=負、
# domain/route.py冒頭コメント参照）。ユーザーが指定した走行方位（travel_bearing_deg）が
# 道路自身の向き（road_bearing_deg）と一致するほど、その道路の勾配をそのまま受ける
# （cos(0)=1）。走行方位が道路の向きの真逆であれば、道路を逆走する想定になるため符号が
# 反転する（cos(180°)=-1、登り坂を逆に辿れば下り坂になる）。直角に近いほど「その道路は
# 指定方向とほぼ交差するだけで、指定方向にはほとんど進まない」とみなし影響を0へ近づける
# （cos(90°)=0、二値反転案[±90°で符号切替]は境界で表示が急に切り替わる不自然さがあるため
# 不採用）。風のwind_drag_ratioと同じ「走行方位との角度差を係数にする」考え方の応用。
#
# ただし**直角に近い範囲は値を0として配らず、そもそも値を持たないものとして扱う**
# （`shows_gradient`）。0%として配ると、その道は地図の凡例で「平坦」の段へ入り、実際には
# 急な坂である道が平坦な道と同じ色で塗られる——読み手はそれを区別できない。指定方向へは
# ほとんど進まない道について言えるのは「この向きでの勾配は示せない」であって「平坦だ」
# ではない。
#
# road_bearing_deg（道路自身の向き）とtravel_bearing_deg（ユーザー指定の走行方位）を
# 入れ替えても結果は同じになる（cosは偶関数のため）。また、同じ道路の逆方向のroad_edges行
# （forward/backward、domain/graph.py参照）を使っても値は変わらない——逆方向は
# road_bearing_deg±180度・gradient_percentの符号反転の両方が起きるため、cos(±180度)=-1との
# 積で符号が2回反転し元に戻る（backend/app/infrastructure/road_graph_repository.py:
# get_feature_gradient_inputs_in_tileがforward/backwardどちらの行を拾っても結果が一致する
# 理由、test_gradient.py: test_forward_and_backward_edge_agreeで検証）。


#: 直角からこの角度以内の道路は、その走行方位での勾配を示さない（地図では「データなし」）。
#: 実地を見て決め直す値で、最初の値には根拠が無い。
LENS_PERPENDICULAR_BAND_DEG = 15.0


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

    @staticmethod
    def shows_gradient(road_bearing_deg: float, travel_bearing_deg: float) -> bool:
        """その走行方位でこの道路の勾配を示せるか（モジュール冒頭のコメント参照）。

        直角に近いほど`effective_gradient`は0へ近づくが、0は「平坦」を意味する値として
        既に使われている。示せない範囲はこの判定で先に落とし、値そのものを配らない。
        """
        # 角度そのもので比べる（cosの大小で比べると、直角の左右で浮動小数の差だけ
        # 判定が食い違う）。180度で畳むのは、逆走（符号が反転するだけ）を同じ扱いに
        # するため。
        folded = (road_bearing_deg - travel_bearing_deg) % 180
        return abs(folded - 90) > LENS_PERPENDICULAR_BAND_DEG
