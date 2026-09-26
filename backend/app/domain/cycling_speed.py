"""自転車の走行モデル（所要時間の物理）。

区間ごとの速度は走行方程式で決まる:

    ホイール出力 P = ( 空気抵抗 + 転がり抵抗 + 重力 ) × 速度
    空気抵抗 = ½ × ρ × CdA × (速度 + 向かい風)²
    転がり抵抗 = Crr × 質量 × g
    重力     = 質量 × g × 勾配

利用者から取る入力は**平地・無風の巡航速度**だけで、そこからホイール出力を逆算する
（`wheel_power_w`）。体重・出力・ケイデンスは一般の利用者が答えられないため、CdA・Crr・質量は
標準値を使う。「向かい風に強い／弱い」の差の多くは巡航速度の違いとして式から出る——同じ
向かい風5m/sでも、巡航20km/hの人は42%、30km/hの人は25%しか落ちない。

**駆動系の伝達効率は掛けない**。巡航速度から逆算するのはホイールでの出力で、他の条件でも
同じ量を使うため相殺される。

速度の逆算は`v`の3次方程式になるため二分法で解く（`SegmentSpeedModel.speed_ms`、numpyでベクトル化）。
探索中には呼ばず、コスト配列を合成するときに区間ごと（風は時刻ビンごと）へ事前計算する。
"""

from dataclasses import dataclass, field

import numpy as np

from app.domain.material_catalog import SURFACE_GOOD
from app.domain.tuning import tuning_value

AIR_DENSITY_KG_M3 = 1.225
GRAVITY_M_S2 = 9.80665

# 走ってみて決める値（CdA・Crr・質量・速度の上下限・登りの出力の増え方等）は
# `domain/tuning.py`が宣言し、ここでは読むだけにする。定数として持つと、宣言と二重に
# なったうえ管理画面からの変更が効かない。

# 速度を挟み込む二分法の反復回数。初期区間は押して歩く速度〜下りの上限（約11m/s）で、
# 12回で幅は0.003m/s（0.01km/h）まで縮む。粗くすると平地・無風で巡航速度に一致しなくなる
# 一方、反復の中で配列を確保し直さないため回数を減らしても速くならない（実測）。
SPEED_SOLVE_ITERATIONS = 12

# 路面の良否を持つ材料id。走行モデルはこれを**軸の構成と無関係に**必要とする
# （`domain/traffic.py: stop_count_material_ids`と同じ理由）。
ROLLING_RESISTANCE_MATERIAL_ID = SURFACE_GOOD


def crr_for_surface(surface_good: np.ndarray | None, length: int) -> np.ndarray:
    """路面の良否（True=舗装良好）から区間ごとの転がり抵抗を、`length`件返す。

    値が無い区間（路面タグ不明、材料そのものが無い）は舗装路として扱う——「タグが無い」を
    「路面が悪い」と読み替えないための既定（`material_catalog.py`の`surface_good`は
    この区別のためだけに`bool_default="nan"`を持つ）。
    """
    paved = tuning_value("speed.crr")
    if surface_good is None:
        return np.full(length, paved)
    values = np.asarray(surface_good, dtype=np.float64)
    if values.shape != (length,):
        raise ValueError(f"路面の材料が区間数と揃っていません 材料={values.shape} 区間={length}")
    return np.where(values == 0.0, tuning_value("speed.unpaved_crr"), paved)


@dataclass(frozen=True)
class RiderProfile:
    """走行モデルの個人パラメータ。利用者が入力するのは巡航速度だけで、残りは標準値。"""

    cruise_speed_kmh: float
    # 標準値は宣言（`domain/tuning.py`）が持つ。既定を評価するのは**生成のたび**で、
    # import時ではない——import時に束ねると、管理画面から変えた値が効かない。
    cda_m2: float = field(default_factory=lambda: tuning_value("speed.cda_m2"))
    crr: float = field(default_factory=lambda: tuning_value("speed.crr"))
    mass_kg: float = field(default_factory=lambda: tuning_value("speed.mass_kg"))

    @property
    def cruise_speed_ms(self) -> float:
        return self.cruise_speed_kmh / 3.6


def wheel_power_w(profile: RiderProfile) -> float:
    """平地・無風の巡航速度からホイール出力（W）を逆算する。"""
    speed = profile.cruise_speed_ms
    drag = 0.5 * AIR_DENSITY_KG_M3 * profile.cda_m2 * speed * speed
    rolling = profile.crr * profile.mass_kg * GRAVITY_M_S2
    return (drag + rolling) * speed


def climb_power_ratio(grade: np.ndarray) -> np.ndarray:
    """登りで出力を何倍にするか。勾配に比例して増え、上限で止まる（下り・平地は1.0）。

    一定出力で計算すると平地20km/hの人が勾配5%で時速4.6km＝押して歩く速度になり現実と
    合わないため、勾配に比例して踏む量を増やす。
    """
    per_grade = tuning_value("speed.climb_power_per_grade")
    return np.clip(
        1.0 + per_grade * np.maximum(grade, 0.0), 1.0, tuning_value("speed.max_climb_power_ratio")
    )


class SegmentSpeedModel:
    """区間ごとの走行モデルのうち、風に依らない部分（出力・速度に依らない抵抗・挟み込みの初期区間）を
    先に1回だけ求めたもの。風の成分を渡すたびに速度を解く。

    時刻ビンごとに変わるのは風だけなので、ルート生成は探索範囲に1回作ってビンの数だけ解く。
    較正値は作った時点で読む。**配列はすべて`grade`と同じ長さで渡す**——長さ1の配列は
    numpyのブロードキャストで全区間へ黙って広がるため、揃っていることをここで確かめる。
    """

    def __init__(self, profile: RiderProfile, grade: np.ndarray, crr: np.ndarray | None = None) -> None:
        """`grade`は勾配（0.05なら5%）。`crr`を渡すと区間ごとに転がり抵抗を変えられる（未舗装等）。"""
        grade = np.asarray(grade, dtype=np.float32)
        rolling_crr = (
            np.full(grade.shape, tuning_value("speed.crr"), dtype=np.float32)
            if crr is None
            else np.asarray(crr, dtype=np.float32)
        )
        if rolling_crr.shape != grade.shape:
            raise ValueError(f"区間の配列の長さが揃っていません grade={grade.shape} crr={rolling_crr.shape}")
        self._shape = grade.shape
        self._power = (wheel_power_w(profile) * climb_power_ratio(grade)).astype(np.float32)
        self._constant_force = (
            rolling_crr * np.float32(profile.mass_kg * GRAVITY_M_S2)
            + np.float32(profile.mass_kg * GRAVITY_M_S2) * grade
        )
        self._drag_coefficient = np.float32(0.5 * AIR_DENSITY_KG_M3 * profile.cda_m2)
        self._lowest_ms = tuning_value("speed.walking_kmh") / 3.6
        self._highest_ms = tuning_value("speed.max_descent_kmh") / 3.6

    def speed_ms(self, headwind_ms: np.ndarray, crosswind_ms: np.ndarray | None = None) -> np.ndarray:
        """区間ごとの走行速度（m/s）。`headwind_ms`は進行方向への向かい風成分（正が向かい風）、
        `crosswind_ms`は横成分。

        走行方程式`P = 抵抗力(v) × v`を`v`について解く。3次方程式になるため、二分法で挟んでから
        解を返す（ニュートン法は抵抗力が0を跨ぐ下り坂で発散しうるため、区間を確実に狭める方を採る）。

        区間数は数十万規模になるため、反復の中では配列を確保し直さず用意したバッファへ書き込む。
        **反復はfloat32で回す**——この解法は計算そのものより配列の読み書きで時間が決まっており
        （実測）、幅を半分にすると比例して速くなる。float32の有効桁は7桁で、二分法が詰める幅
        （0.003m/s）より4桁細かい。
        """
        headwind = np.asarray(headwind_ms, dtype=np.float32)
        cross = (
            np.zeros(self._shape, dtype=np.float32)
            if crosswind_ms is None
            else np.asarray(crosswind_ms, dtype=np.float32)
        )
        mismatched = {
            name: array.shape
            for name, array in (("headwind_ms", headwind), ("crosswind_ms", cross))
            if array.shape != self._shape
        }
        if mismatched:
            raise ValueError(f"区間の配列の長さが揃っていません grade={self._shape} {mismatched}")
        power = self._power
        constant_force = self._constant_force
        drag_coefficient = self._drag_coefficient
        cross_squared = cross * cross

        low = np.full(self._shape, self._lowest_ms, dtype=np.float32)
        high = np.full(self._shape, self._highest_ms, dtype=np.float32)
        middle = np.empty_like(low)
        along = np.empty_like(low)
        scratch = np.empty_like(low)
        too_fast = np.empty(low.shape, dtype=bool)
        for _ in range(SPEED_SOLVE_ITERATIONS):
            np.add(low, high, out=middle)
            np.multiply(middle, np.float32(0.5), out=middle)
            np.add(middle, headwind, out=along)
            np.multiply(along, along, out=scratch)
            np.add(scratch, cross_squared, out=scratch)
            np.sqrt(scratch, out=scratch)
            np.multiply(scratch, along, out=scratch)
            np.multiply(scratch, drag_coefficient, out=scratch)
            np.add(scratch, constant_force, out=scratch)
            np.multiply(scratch, middle, out=scratch)
            # 必要な出力が持っている出力を超えるなら、その速度は出せない（上限を下げる）。
            np.greater(scratch, power, out=too_fast)
            np.copyto(high, middle, where=too_fast)
            np.copyto(low, middle, where=~too_fast)
        np.add(low, high, out=middle)
        np.multiply(middle, np.float32(0.5), out=middle)
        # 呼び出し側（コスト配列・所要時間）はfloat64で揃えてある。
        return middle.astype(np.float64)

    def travel_seconds(
        self, distance_m: np.ndarray, headwind_ms: np.ndarray, crosswind_ms: np.ndarray | None = None
    ) -> np.ndarray:
        """区間ごとの走行時間（秒）。停止・ターンの待ちは含まない（別に足す）。"""
        distance = np.asarray(distance_m, dtype=np.float64)
        speed = self.speed_ms(headwind_ms, crosswind_ms)
        if distance.shape != speed.shape:
            raise ValueError(f"距離が区間数と揃っていません 距離={distance.shape} 区間={speed.shape}")
        return distance / speed
