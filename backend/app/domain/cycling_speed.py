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

速度の逆算は`v`の3次方程式になるためニュートン法で解く（`speed_ms`、numpyでベクトル化）。
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


def _resistance_force(
    speed: np.ndarray, grade: np.ndarray, headwind_ms: np.ndarray, profile: RiderProfile, crr: np.ndarray
) -> np.ndarray:
    """その速度で釣り合う抵抗力の合計（N）。向かい風は正、追い風は負。"""
    apparent = speed + headwind_ms
    # 追い風が速度を上回る（見かけの風が後ろから）場合も抵抗は正にならず推進側へ効く。
    drag = 0.5 * AIR_DENSITY_KG_M3 * profile.cda_m2 * apparent * np.abs(apparent)
    rolling = crr * profile.mass_kg * GRAVITY_M_S2
    gravity = profile.mass_kg * GRAVITY_M_S2 * grade
    return drag + rolling + gravity


def speed_ms(
    profile: RiderProfile,
    grade: np.ndarray,
    headwind_ms: np.ndarray,
    crr: np.ndarray | None = None,
    iterations: int = 12,
) -> np.ndarray:
    """区間ごとの走行速度（m/s）。`grade`は勾配（0.05なら5%）、`headwind_ms`は進行方向への
    向かい風成分（正が向かい風）。`crr`を渡すと区間ごとに転がり抵抗を変えられる（未舗装等）。

    走行方程式`P = 抵抗力(v) × v`を`v`について解く。3次方程式になるため、二分法で挟んでから
    解を返す（ニュートン法は抵抗力が0を跨ぐ下り坂で発散しうるため、区間を確実に狭める方を採る）。
    """
    grade = np.asarray(grade, dtype=np.float64)
    headwind = np.asarray(headwind_ms, dtype=np.float64)
    rolling = np.full(grade.shape, DEFAULT_CRR) if crr is None else np.asarray(crr, dtype=np.float64)
    power = wheel_power_w(profile) * climb_power_ratio(grade)

    low = np.full(grade.shape, WALKING_SPEED_KMH / 3.6)
    high = np.full(grade.shape, MAX_DESCENT_SPEED_KMH / 3.6)
    for _ in range(iterations):
        middle = (low + high) / 2
        needed = _resistance_force(middle, grade, headwind, profile, rolling) * middle
        # 必要な出力が持っている出力を超えるなら、その速度は出せない（上限を下げる）。
        too_fast = needed > power
        high = np.where(too_fast, middle, high)
        low = np.where(too_fast, low, middle)
    return (low + high) / 2


def travel_seconds(
    distance_m: np.ndarray,
    profile: RiderProfile,
    grade: np.ndarray,
    headwind_ms: np.ndarray,
    crr: np.ndarray | None = None,
) -> np.ndarray:
    """区間ごとの走行時間（秒）。停止・ターンの待ちは含まない（別に足す）。"""
    return np.asarray(distance_m, dtype=np.float64) / speed_ms(profile, grade, headwind_ms, crr)
