import math

# domain/wind.py: wind_drag_ratioと同型の「向きに依存する動的材料」の純粋計算ロジック。
#
# gradient_percentは道路自身の始点→終点方向を基準にした符号付き値（登り=正、下り=負、
# domain/route.py冒頭コメント参照）。
#
# **走行方位が決めるのは符号だけで、坂の急さは変えない。** 道路は道路に沿ってしか走れず、
# その道を走るときの進行方向は道路の向きそのものだからである。走行方位（ユーザーが
# コンパスで指定する、全体としてどちらへ向かうか）は「この道をどちら向きに辿るか」を
# 決めるだけで、辿る以上は坂の急さをそのまま受ける。
#
# 角度差を係数に掛ける（cos投影）と、同じ坂が方位次第で緩く見える。15%の坂は、どの方位を
# 選んでいても15%の坂である。風（wind_drag_ratio）は風向が進行方向と独立に決まるため
# 角度差が実際に抗力を変えるが、勾配では道路の向きが進行方向そのもののため同じ扱いはできない。
#
# 直角に近い範囲は符号が決まらない（どちら向きにも辿れる）。そこは値を持たないものとして
# 扱う（`shows_gradient`）——0%として配ると、その道は地図の凡例で「平坦」の段へ入り、
# 実際には急な坂である道が平坦な道と同じ色で塗られる。言えるのは「この向きでの勾配は
# 示せない」であって「平坦だ」ではない。
#
# 同じ道路の逆方向のroad_edges行（forward/backward、domain/graph.py参照）を使っても値は
# 変わらない——逆方向はroad_bearing_deg±180度・gradient_percentの符号反転の両方が起きる
# ため、符号が2回反転して元に戻る（backend/app/infrastructure/road_graph_repository.py:
# get_feature_gradient_inputs_in_tileがforward/backwardどちらの行を拾っても結果が一致する
# 理由、test_gradient.py: test_forward_and_backward_edge_agreeで検証）。


#: 直角からこの角度以内の道路は、その走行方位での勾配を示さない（地図では「データなし」）。
#: 実地を見て決め直す値で、最初の値には根拠が無い。
LENS_PERPENDICULAR_BAND_DEG = 15.0


class GradientCalculator:
    """道路自身の勾配・向きと、ユーザーが指定した走行方位から、その道をその向きに辿った
    場合の勾配（%）を求める。

    正の値=登り、負の値=下り。大きさは道路自身の勾配のままで、走行方位では変わらない
    （モジュール冒頭のコメント参照）。
    """

    @staticmethod
    def effective_gradient(gradient_percent: float, road_bearing_deg: float, travel_bearing_deg: float) -> float:
        diff = math.radians(road_bearing_deg - travel_bearing_deg)
        # 符号だけを決める。道路の向き寄りならそのまま、逆向き寄りなら登り下りが入れ替わる。
        return gradient_percent if math.cos(diff) >= 0 else -gradient_percent

    @staticmethod
    def shows_gradient(road_bearing_deg: float, travel_bearing_deg: float) -> bool:
        """その走行方位でこの道路の勾配を示せるか（モジュール冒頭のコメント参照）。

        直角に近いと、その道をどちら向きに辿るかが決まらず符号を選べない。示せない範囲は
        この判定で先に落とし、値そのものを配らない。
        """
        # 角度そのもので比べる（cosの大小で比べると、直角の左右で浮動小数の差だけ
        # 判定が食い違う）。180度で畳むのは、逆走（符号が反転するだけ）を同じ扱いに
        # するため。
        folded = (road_bearing_deg - travel_bearing_deg) % 180
        return abs(folded - 90) > LENS_PERPENDICULAR_BAND_DEG
