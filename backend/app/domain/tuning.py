"""較正値（走ってみて決める値）の宣言。

探索のコストモデルには、実感に合わせて置いたまま較正されていない値が多数ある。どれもコードの定数で、
変えるにはデプロイが要る。較正は実走してみないと決まらない性質のため、デプロイなしで回せないと
収束しない。

**この宣言が唯一の母集団**である。エンジンが読む値・管理画面が並べる項目・変更が効くために
何をやり直す必要があるかは、すべてここから導く。変えられるようにする対象と管理画面が面倒を
見る対象を別々に決めると必ずズレるため、宣言を1つにする。

**「宣言に載せる」と「管理画面から変えられる」は別**である。載せるのはルーティング評価が使う
固定値すべてで、そのうち管理画面へ出るのは種別が`CALIBRATION`のものだけ。物理定数を画面へ
出すと模型を壊せてしまい、資源の上限を出すと本番を止められる。両者を1つの宣言に置いたうえで
種別で分けることで、「この値はどこで決まっていて、変えられるのか」の答えが1箇所になる。
"""

from dataclasses import dataclass
from enum import Enum


class TuningKind(Enum):
    """その固定値が何であるか。**管理画面へ出るのは`CALIBRATION`だけ**。"""

    #: 走ってみて決める値。実感に合わせて置いてあり、較正が要る。
    CALIBRATION = "calibration"
    #: 物理定数。決まった値で、較正の対象ではない。
    PHYSICAL = "physical"
    #: 数値解法・実装の都合で決めた値。変えても模型は変わらず、精度と速度が動く。
    NUMERICAL = "numerical"
    #: 資源の上限。暴走を止めるための budget で、画面から緩めると本番が止まる。
    BUDGET = "budget"
    #: 外部データの刻み等、こちらの都合では決められない値。
    EXTERNAL = "external"
    #: 変えると事前集計のやり直しが要る値（デプロイなしで回す枠に入らない）。
    PRECOMPUTED = "precomputed"


class TuningEffect(Enum):
    """値を変えたとき、効くまでに何が要るか。

    **「変えたのに効かない」を宣言として持つ**。変更の反映に別の操作が要る値が混ざっている
    のに画面が同じ見た目だと、効いていないことに気づけない。
    """

    #: 次のリクエストから効く（リクエストごとのコスト合成が読む）。
    IMMEDIATE = "immediate"
    #: 探索木のプロセス内キャッシュが値で鍵を持つため、作り直しは自動で起きる。
    TURN_STRUCTURE = "turn_structure"
    #: `road_nodes`の事前計算バッチをやり直さないと効かない。
    NODE_ATTRIBUTE_BATCH = "node_attribute_batch"
    #: プロセスを入れ替えないと効かない（APIスキーマの既定値のように、import時に束ねられる）。
    RESTART = "restart"


@dataclass(frozen=True)
class TuningParameter:
    """較正値1つぶんの宣言。"""

    id: str
    #: 何の値か。管理画面へ出るのは`CALIBRATION`だけ。
    kind: TuningKind
    #: 管理画面の表示名。
    label: str
    #: 単位（管理画面が値の右に出す）。無次元の比率等は空。
    unit: str
    default: float
    #: 桁を間違えたときに止めるための範囲であって、**意味的な歯止めではない**
    #: （`axis_admin`が重みに歯止めを設けないのと同じ考え方）。
    minimum: float
    maximum: float
    effect: TuningEffect
    #: 何を決める値か。管理画面のⓘへ出す。
    description: str


def _stop_parameter(kind: str, label: str, default: float, description: str) -> TuningParameter:
    """停止要因1種別ぶんの宣言。idは種別の綴りから導く（`POI_COUNT_KINDS`と1対1）。"""
    return TuningParameter(
        id=f"stop.{kind}_seconds",
        kind=TuningKind.CALIBRATION,
        label=f"{label}の待ち",
        unit="秒",
        default=default,
        minimum=0.0,
        maximum=300.0,
        effect=TuningEffect.IMMEDIATE,
        description=description,
    )


TUNING_PARAMETERS: tuple[TuningParameter, ...] = (
    # --- ターンの費用（方位差だけで決めた暫定値） ---
    TuningParameter(
        "turn.left_seconds",
        TuningKind.CALIBRATION,
        "左折", "秒", 2.0, 0.0, 120.0, TuningEffect.TURN_STRUCTURE,
        "左折1回の時間損失。探索のコストも秒のため、走行時間と直接比べられる。",
    ),
    TuningParameter(
        "turn.right_seconds",
        TuningKind.CALIBRATION,
        "右折", "秒", 12.0, 0.0, 120.0, TuningEffect.TURN_STRUCTURE,
        "右折1回の時間損失。対向を待つぶん左折より大きい。",
    ),
    TuningParameter(
        "turn.uturn_seconds",
        TuningKind.CALIBRATION,
        "Uターン", "秒", 60.0, 0.0, 600.0, TuningEffect.TURN_STRUCTURE,
        "来た道を折り返す1回の時間損失。実質的に選ばせないための大きな値。",
    ),
    TuningParameter(
        "turn.straight_max_deg",
        TuningKind.CALIBRATION,
        "直進とみなす方位差", "度", 30.0, 0.0, 90.0,
        TuningEffect.TURN_STRUCTURE,
        "この角度までの曲がりは直進とみなし、ターンの費用を足さない。",
    ),
    TuningParameter(
        "turn.major_crossing_seconds",
        TuningKind.CALIBRATION,
        "上位の道の横断", "秒", 8.0, 0.0, 300.0,
        TuningEffect.TURN_STRUCTURE,
        "信号の無い交差点で、進入した道より上位の階級の道を直進で渡るときに足す。"
        "信号のある交差点の待ちは停止要因の側が数えるため、ここでは足さない。",
    ),
    TuningParameter(
        "turn.major_turn_seconds",
        TuningKind.CALIBRATION,
        "上位の道への右左折", "秒", 15.0, 0.0, 300.0,
        TuningEffect.TURN_STRUCTURE,
        "信号の無い交差点で、上位の階級の道へ右左折で入るときに足す。",
    ),
    # --- 停止要因の待ち（種別はPOI_COUNT_KINDSが正本） ---
    _stop_parameter("signal", "信号", 21.0, "一般的な信号サイクルからの見積もり。"),
    _stop_parameter("crossing", "信号なしの横断歩道", 0.0,
                    "信号の無い横断歩道。自転車が止まる前提を置いていないため既定は0秒。"),
    _stop_parameter("stop", "一時停止・徐行", 8.0, "一時停止の標識・標示で減速して止まるぶん。"),
    _stop_parameter("level_crossing", "踏切", 25.0, "遮断機の待ちを含む見積もり。"),
    _stop_parameter("barrier", "車止め・減速構造", 8.0, "車止め・ボラード等で減速するぶん。"),
    # --- 交差点の信号判定 ---
    TuningParameter(
        "signal.match_radius_m",
        TuningKind.CALIBRATION,
        "信号とみなす半径", "m", 40.0, 1.0, 200.0,
        TuningEffect.NODE_ATTRIBUTE_BATCH,
        "交差点ノードから何m以内の信号を、その交差点の信号とみなすか。"
        "広げるほど「信号が無いのに上位の道を渡る」とみなす交差点が減り、横断の費用が付かなくなる"
        "（幹線が集まる交差点で信号ありとみなす割合は10mで37.4%・60mで67.9%、頭打ちが無い）。",
    ),
    # --- 走行モデル ---
    TuningParameter(
        "speed.cda_m2",
        TuningKind.CALIBRATION,
        "空気抵抗係数×前面投影面積", "m²", 0.32, 0.1, 1.0, TuningEffect.IMMEDIATE,
        "ロードバイクのブラケットポジションの標準値。",
    ),
    TuningParameter(
        "speed.crr",
        TuningKind.CALIBRATION,
        "転がり抵抗（舗装路）", "", 0.005, 0.001, 0.05, TuningEffect.IMMEDIATE,
        "舗装路の23〜28mmタイヤの標準値。",
    ),
    TuningParameter(
        "speed.unpaved_crr",
        TuningKind.CALIBRATION,
        "転がり抵抗（未舗装）", "", 0.015, 0.001, 0.1, TuningEffect.IMMEDIATE,
        "砂利・締固めの一般的な値域（0.012〜0.020）の中ほど。"
        "平地・無風で巡航20km/hの人が約14km/hになる。",
    ),
    TuningParameter(
        "speed.mass_kg",
        TuningKind.CALIBRATION,
        "総質量", "kg", 80.0, 30.0, 200.0, TuningEffect.IMMEDIATE,
        "体重＋車体＋装備の目安。",
    ),
    TuningParameter(
        "speed.max_descent_kmh",
        TuningKind.CALIBRATION,
        "下りの速度上限", "km/h", 45.0, 10.0, 100.0,
        TuningEffect.IMMEDIATE,
        "下りで際限なく速くならないための上限。入れないと急勾配で所要時間が発散する。",
    ),
    TuningParameter(
        "speed.walking_kmh",
        TuningKind.CALIBRATION,
        "押して歩く速度", "km/h", 4.5, 1.0, 10.0, TuningEffect.IMMEDIATE,
        "登りでこれ以下になったら押して歩くとみなす下限。",
    ),
    TuningParameter(
        "speed.climb_power_per_grade",
        TuningKind.CALIBRATION,
        "登りの出力の増え方", "W/%", 25.0, 0.0, 200.0,
        TuningEffect.IMMEDIATE,
        "勾配1%あたり何W余分に踏むか。勾配5%で時速10km・10%で時速6km前後という実感に"
        "合わせた暫定値で、根拠は薄い。",
    ),
    TuningParameter(
        "speed.max_climb_power_ratio",
        TuningKind.CALIBRATION,
        "登りの出力の上限倍率", "倍", 2.5, 1.0, 10.0,
        TuningEffect.IMMEDIATE,
        "平地の巡航に対して何倍まで踏むか。上の増え方をここで頭打ちにする。",
    ),
    # --- 主観と時間の換算 ---
    TuningParameter(
        "evaluation.penalty_strength",
        TuningKind.CALIBRATION,
        "主観と時間の換算レート", "", 0.7, 0.0, 5.0,
        TuningEffect.RESTART,
        "評価軸の難易度を所要時間の割増しへ換算する強さの既定値。"
        "リクエストごとに上書きできるため、ここで決めるのは省略されたときの値だけ。",
    ),
)


#: 宣言の逆引き。
TUNING_PARAMETERS_BY_ID: dict[str, TuningParameter] = {p.id: p for p in TUNING_PARAMETERS}

#: いま効いている値（id → 値）。既定で初期化し、DBの上書きを読み込んだときに**中身だけ**を
#: 差し替える（束縛済みの参照先が古いままにならないよう、`.clear()`+`.update()`で更新する。
#: `services/axis_registry_service.py`が`AXIS_DEFINITIONS`へ採っているのと同じ流儀）。
TUNING_VALUES: dict[str, float] = {p.id: p.default for p in TUNING_PARAMETERS}


def calibration_parameters() -> tuple[TuningParameter, ...]:
    """管理画面が並べる項目（＝較正値だけ）。画面側で種別を数え上げない。"""
    return tuple(p for p in TUNING_PARAMETERS if p.kind is TuningKind.CALIBRATION)


def tuning_value(param_id: str) -> float:
    """いま効いている較正値。宣言に無いidは呼び出し側の綴り間違いなので落とす。"""
    try:
        return TUNING_VALUES[param_id]
    except KeyError:
        raise KeyError(f"較正値の宣言に無いid: {param_id}") from None


def stop_seconds_parameter_id(kind: str) -> str:
    """停止要因の種別から較正値のid（綴りを組み立てる場所を1つにする）。"""
    return f"stop.{kind}_seconds"


def turn_parameter_ids() -> tuple[str, ...]:
    """ターンの費用の較正値id（`TurnCostSpec`の組み立てが使う）。"""
    return tuple(p.id for p in TUNING_PARAMETERS if p.id.startswith("turn."))


__all__ = [
    "TUNING_PARAMETERS",
    "TUNING_PARAMETERS_BY_ID",
    "TUNING_VALUES",
    "TuningEffect",
    "TuningKind",
    "TuningParameter",
    "calibration_parameters",
    "stop_seconds_parameter_id",
    "tuning_value",
    "turn_parameter_ids",
]
