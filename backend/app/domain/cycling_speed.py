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
同じ量を使うため相殺される。外部の出力値（FTP等）を入力させるようになったら入れる。

速度の逆算は`v`の3次方程式になるため二分法で解く（`speed_ms`、numpyでベクトル化）。
探索中には呼ばず、コスト配列を合成するときに区間ごと（風は時刻ビンごと）へ事前計算する。
"""

from dataclasses import dataclass

import numpy as np

AIR_DENSITY_KG_M3 = 1.225
GRAVITY_M_S2 = 9.80665

# 標準値（段階1では利用者に聞かない）。CdAはロードバイクのブラケットポジション、Crrは舗装路の
# 23〜28mmタイヤ、質量は体重＋車体＋装備の目安。
DEFAULT_CDA_M2 = 0.32
DEFAULT_CRR = 0.005
DEFAULT_MASS_KG = 80.0

# 下りで際限なく速くならないための上限と、登りでこれ以下になったら押して歩くとみなす下限。
# 入れないと急勾配で所要時間が発散する。
MAX_DESCENT_SPEED_KMH = 45.0
WALKING_SPEED_KMH = 4.5

# 登りでは平地の巡航より踏む（一定出力で計算すると、平地20km/hの人が勾配5%で時速4.6km＝押して
# 歩く速度になり現実と合わない）。勾配に比例して出力を増やし、上限で止める。
# **この2つの値の根拠は薄い**——勾配5%で時速10km・10%で時速6km前後という一般的な実感に
# 合わせた暫定値で、実走データでの較正が要る。
CLIMB_POWER_PER_GRADE = 25.0
MAX_CLIMB_POWER_RATIO = 2.5
# 速度を挟み込む二分法の反復回数。初期区間は押して歩く速度〜下りの上限（約11m/s）で、
# 12回で幅は0.003m/s（0.01km/h）まで縮む。粗くすると平地・無風で巡航速度に一致しなくなる
# 一方、反復の中で配列を確保し直さないため回数を減らしても速くならない（実測）。
SPEED_SOLVE_ITERATIONS = 12

# 未舗装路の転がり抵抗。`DEFAULT_CRR`（舗装路の23〜28mmタイヤ）の3倍で、砂利・締固めの
# 一般的な値域（0.012〜0.020）の中ほどを採る。平地・無風で巡航20km/hの人が約14km/hになる。
# **実走データでの較正が要る暫定値**（`CLIMB_POWER_PER_GRADE`等と同じ扱い）。
UNPAVED_CRR = 0.015

# 路面の良否を持つ材料id。走行モデルはこれを**軸の構成と無関係に**必要とする
# （`domain/traffic.py: stop_count_material_ids`と同じ理由）。
ROLLING_RESISTANCE_MATERIAL_ID = "surface_good"


def crr_for_surface(surface_good: np.ndarray | None, length: int) -> np.ndarray:
    """路面の良否（True=舗装良好）から区間ごとの転がり抵抗を返す。

    値が無い区間（路面タグ不明、材料そのものが無い）は舗装路として扱う——「タグが無い」を
    「路面が悪い」と読み替えないための既定（`material_catalog.py`の`surface_good`は
    この区別のためだけに`bool_default="nan"`を持つ）。
    """
    if surface_good is None:
        return np.full(length, DEFAULT_CRR)
    values = np.asarray(surface_good, dtype=np.float64)
    return np.where(values == 0.0, UNPAVED_CRR, DEFAULT_CRR)


@dataclass(frozen=True)
class RiderProfile:
    """走行モデルの個人パラメータ。段階1は巡航速度だけが利用者の入力で、残りは標準値。"""

    cruise_speed_kmh: float
    cda_m2: float = DEFAULT_CDA_M2
    crr: float = DEFAULT_CRR
    mass_kg: float = DEFAULT_MASS_KG

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
    """登りで出力を何倍にするか。勾配に比例して増え、`MAX_CLIMB_POWER_RATIO`で止まる
    （下り・平地は1.0）。"""
    return np.clip(1.0 + CLIMB_POWER_PER_GRADE * np.maximum(grade, 0.0), 1.0, MAX_CLIMB_POWER_RATIO)


def speed_ms(
    profile: RiderProfile,
    grade: np.ndarray,
    headwind_ms: np.ndarray,
    crosswind_ms: np.ndarray | None = None,
    crr: np.ndarray | None = None,
    iterations: int = SPEED_SOLVE_ITERATIONS,
) -> np.ndarray:
    """区間ごとの走行速度（m/s）。`grade`は勾配（0.05なら5%）、`headwind_ms`は進行方向への
    向かい風成分（正が向かい風）、`crosswind_ms`は横成分。`crr`を渡すと区間ごとに転がり抵抗を
    変えられる（未舗装等）。

    走行方程式`P = 抵抗力(v) × v`を`v`について解く。3次方程式になるため、二分法で挟んでから
    解を返す（ニュートン法は抵抗力が0を跨ぐ下り坂で発散しうるため、区間を確実に狭める方を採る）。

    リクエストごとに時刻ビンの本数ぶん呼ばれ、区間数は数十万規模になるため、反復の中では
    配列を確保し直さず用意したバッファへ書き込む。**反復はfloat32で回す**——この解法は
    計算そのものより配列の読み書きで時間が決まっており（実測）、幅を半分にすると比例して
    速くなる。float32の有効桁は7桁で、二分法が詰める幅（0.003m/s）より4桁細かい。
    """
    grade = np.asarray(grade, dtype=np.float32)
    headwind = np.asarray(headwind_ms, dtype=np.float32)
    rolling_crr = (
        np.full(grade.shape, DEFAULT_CRR, dtype=np.float32)
        if crr is None
        else np.asarray(crr, dtype=np.float32)
    )
    cross = (
        np.zeros(grade.shape, dtype=np.float32)
        if crosswind_ms is None
        else np.asarray(crosswind_ms, dtype=np.float32)
    )
    power = (wheel_power_w(profile) * climb_power_ratio(grade)).astype(np.float32)
    # 速度に依らない抵抗（転がり＋重力）は反復の外で1回だけ求める。
    constant_force = (
        rolling_crr * np.float32(profile.mass_kg * GRAVITY_M_S2)
        + np.float32(profile.mass_kg * GRAVITY_M_S2) * grade
    )
    drag_coefficient = np.float32(0.5 * AIR_DENSITY_KG_M3 * profile.cda_m2)
    cross_squared = cross * cross

    low = np.full(grade.shape, WALKING_SPEED_KMH / 3.6, dtype=np.float32)
    high = np.full(grade.shape, MAX_DESCENT_SPEED_KMH / 3.6, dtype=np.float32)
    middle = np.empty_like(low)
    along = np.empty_like(low)
    scratch = np.empty_like(low)
    too_fast = np.empty(low.shape, dtype=bool)
    for _ in range(iterations):
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
    distance_m: np.ndarray,
    profile: RiderProfile,
    grade: np.ndarray,
    headwind_ms: np.ndarray,
    crosswind_ms: np.ndarray | None = None,
    crr: np.ndarray | None = None,
) -> np.ndarray:
    """区間ごとの走行時間（秒）。停止・ターンの待ちは含まない（別に足す）。"""
    return np.asarray(distance_m, dtype=np.float64) / speed_ms(profile, grade, headwind_ms, crosswind_ms, crr)


