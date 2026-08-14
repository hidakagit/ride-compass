import math


class WindCalculator:
    """走行方位と風向風速から、走行への風の影響（ペナルティ）を計算する。

    正の値=向かい風（走行が重くなる）、負の値=追い風（走行が楽になる）、0付近=横風（影響小）。
    進行方向に平行な風成分のみが走行に影響するというモデル。
    """

    @staticmethod
    def wind_penalty(wind_speed_ms: float, wind_direction_deg: float, travel_bearing_deg: float) -> float:
        # wind_direction_degは気象学の慣習で「風が吹いてくる方向」。
        # 走行方位と風向の差が0（風が正面から吹いてくる）＝向かい風＝cos(0)=1で最大。
        # 差が180度（風が背後から吹いてくる＝追い風）＝cos(180)=-1。
        diff = math.radians(wind_direction_deg - travel_bearing_deg)
        return wind_speed_ms * math.cos(diff)
