import math

# gradient_percentは道路自身の始点→終点方向を基準にした符号付き値（登り=正、下り=負）。
#
# **走行方位が決めるのは符号だけで、坂の急さは変えない。** 道路は道路に沿ってしか走れず、
# 辿る以上は坂の急さをそのまま受けるためである。角度差を係数に掛ける（cos投影）と、同じ坂が
# 方位次第で緩く見える。風（wind.py: wind_drag_ratio）は風向が進行方向と独立に決まるため
# 角度差が実際に抗力を変えるが、勾配では道路の向きが進行方向そのもののため同じ扱いはできない。
#
# 直角に近い範囲は符号が決まらない（どちら向きにも辿れる）。そこは値を持たないものとして
# 扱う（`shows_gradient`）——0%として配ると、その道は地図の凡例で「平坦」の段へ入り、
# 実際には急な坂である道が平坦な道と同じ色で塗られる。言えるのは「この向きでの勾配は
# 示せない」であって「平坦だ」ではない。
#
# 同じ道路の逆方向のroad_edges行（forward/backward）を使っても値は変わらない——逆方向は
# road_bearing_deg±180度・gradient_percentの符号反転の両方が起きるため、符号が2回反転して
# 元に戻る。


#: 直角からこの角度以内の道路は、その走行方位での勾配を示さない（地図では「データなし」）。
LENS_PERPENDICULAR_BAND_DEG = 15.0


class GradientCalculator:
    """道路自身の勾配・向きと、ユーザーが指定した走行方位から、その道をその向きに辿った
    場合の勾配（%）を求める。"""

    @staticmethod
    def effective_gradient(gradient_percent: float, road_bearing_deg: float, travel_bearing_deg: float) -> float:
        diff = math.radians(road_bearing_deg - travel_bearing_deg)
        # 符号だけを決める。道路の向き寄りならそのまま、逆向き寄りなら登り下りが入れ替わる。
        return gradient_percent if math.cos(diff) >= 0 else -gradient_percent

    @staticmethod
    def shows_gradient(road_bearing_deg: float, travel_bearing_deg: float) -> bool:
        """その走行方位でこの道路の勾配を示せるか。

        直角に近いと、その道をどちら向きに辿るかが決まらず符号を選べない。示せない範囲は
        この判定で先に落とし、値そのものを配らない。
        """
        # 角度そのもので比べる（cosの大小で比べると、直角の左右で浮動小数の差だけ
        # 判定が食い違う）。180度で畳むのは、逆走（符号が反転するだけ）を同じ扱いに
        # するため。
        folded = (road_bearing_deg - travel_bearing_deg) % 180
        return abs(folded - 90) > LENS_PERPENDICULAR_BAND_DEG
