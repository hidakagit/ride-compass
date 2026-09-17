"""ルーティング評価が読む固定値の宣言。

探索のコストモデルには、実感に合わせて置いたまま較正されていない値が多数ある。どれもコードの定数で、
変えるにはデプロイが要る。較正は実走してみないと決まらない性質のため、デプロイなしで回せないと
収束しない。

**変えられる値（較正値）はここが唯一の正本**である。`TUNING_PARAMETERS`が既定・範囲・単位を
持ち、エンジンが読む値・管理画面が並べる項目・変更が効くために何をやり直す必要があるかを、
すべてそこから導く。変えられるようにする対象と管理画面が面倒を見る対象を別々に決めると必ず
ズレるため、宣言を1つにする。

**変えられない固定値は`FIXED_VALUES`が名前と種別だけを持つ**。値そのものと根拠は使う側の
モジュールに置いたままにする——根拠の文はその値の隣にあってこそ読めるもので、こちらへ写すと
二重管理になる。こちらが持つのは「較正値ではない」という分類だけで、物理定数を画面へ出すと
模型を壊せ、資源の上限を出すと本番を止められる、という線引きがそのまま種別になっている。

2つ合わせて**ルーティング評価が読む固定値の母集団**になる。`scripts/review_checks.py`の
`undeclared_fixed_values`が、`FIXED_VALUES`が挙げるモジュールの直下に**どちらの宣言にも
無い数値定数**があれば落とす——「この値はどこで決まっていて、変えられるのか」の答えが
1箇所にある状態を、書き手の心がけではなく機械で保つ。
"""

from dataclasses import dataclass
from enum import Enum


class FixedValueKind(Enum):
    """較正値ではない固定値が、何であるか（＝なぜ画面から変えさせないか）。

    較正値かどうかはどちらの宣言に載っているかが表すため、この列挙は較正値を持たない。
    """

    #: 物理定数。決まった値で、較正の対象ではない。
    PHYSICAL = "physical"
    #: 数値解法・実装の都合で決めた値。変えても模型は変わらず、精度と速度が動く。
    NUMERICAL = "numerical"
    #: 資源の上限。暴走を止めるためのもので、画面から緩めると本番が止まる。
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
    """較正値1つぶんの宣言（**この宣言に載っている＝管理画面から変えられる**）。"""

    id: str
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
        "左折", "秒", 2.0, 0.0, 120.0, TuningEffect.TURN_STRUCTURE,
        "左折1回の損失。探索のコストも秒で、走行時間と直接比べられる。",
    ),
    TuningParameter(
        "turn.right_seconds",
        "右折", "秒", 12.0, 0.0, 120.0, TuningEffect.TURN_STRUCTURE,
        "右折1回の損失。対向を待つぶん左折より大きい。",
    ),
    TuningParameter(
        "turn.uturn_seconds",
        "Uターン", "秒", 60.0, 0.0, 600.0, TuningEffect.TURN_STRUCTURE,
        "折り返し1回の損失。実質的に選ばせないための大きな値。",
    ),
    TuningParameter(
        "turn.straight_max_deg",
        "直進とみなす方位差", "度", 30.0, 0.0, 90.0,
        TuningEffect.TURN_STRUCTURE,
        "この角度までの曲がりは直進とみなし、費用を足さない。",
    ),
    TuningParameter(
        "turn.major_crossing_seconds",
        "上位の道の横断", "秒", 8.0, 0.0, 300.0,
        TuningEffect.TURN_STRUCTURE,
        "信号の無い交差点で、上位の階級の道を直進で渡るときに足す"
        "（信号のある交差点の待ちは停止要因の側が数える）。",
    ),
    TuningParameter(
        "turn.major_turn_seconds",
        "上位の道への右左折", "秒", 15.0, 0.0, 300.0,
        TuningEffect.TURN_STRUCTURE,
        "信号の無い交差点で、上位の階級の道へ右左折で入るときに足す。",
    ),
    # --- 停止要因の待ち（種別はPOI_COUNT_KINDSが正本） ---
    _stop_parameter("signal", "信号", 21.0, "一般的な信号サイクルからの見積もり。"),
    _stop_parameter("crossing", "信号なし横断歩道", 0.0,
                    "自転車が止まる前提を置いていないため既定は0秒。"),
    _stop_parameter("stop", "一時停止・徐行", 8.0, "標識・標示で減速して止まるぶん。"),
    _stop_parameter("level_crossing", "踏切", 25.0, "遮断機の待ちを含む見積もり。"),
    _stop_parameter("barrier", "車止め・減速構造", 8.0, "ボラード等で減速するぶん。"),
    # --- 交差点の信号判定 ---
    TuningParameter(
        "signal.match_radius_m",
        "信号とみなす半径", "m", 40.0, 1.0, 200.0,
        TuningEffect.NODE_ATTRIBUTE_BATCH,
        "交差点から何m以内の信号を、その交差点のものとみなすか。"
        "広げるほど横断の費用が付く交差点が減る（頭打ちが無い）。",
    ),
    # --- 走行モデル ---
    TuningParameter(
        "speed.cda_m2",
        "空気抵抗 CdA", "m²", 0.32, 0.1, 1.0, TuningEffect.IMMEDIATE,
        "ロードバイクのブラケットポジションの標準値。",
    ),
    TuningParameter(
        "speed.crr",
        "転がり抵抗（舗装路）", "", 0.005, 0.001, 0.05, TuningEffect.IMMEDIATE,
        "舗装路の23〜28mmタイヤの標準値。",
    ),
    TuningParameter(
        "speed.unpaved_crr",
        "転がり抵抗（未舗装）", "", 0.015, 0.001, 0.1, TuningEffect.IMMEDIATE,
        "砂利・締固めの値域（0.012〜0.020）の中ほど。"
        "平地・無風で巡航20km/hの人が約14km/hになる。",
    ),
    TuningParameter(
        "speed.mass_kg",
        "総質量", "kg", 80.0, 30.0, 200.0, TuningEffect.IMMEDIATE,
        "体重＋車体＋装備。",
    ),
    TuningParameter(
        "speed.max_descent_kmh",
        "下りの速度上限", "km/h", 45.0, 10.0, 100.0,
        TuningEffect.IMMEDIATE,
        "入れないと急勾配で所要時間が発散する。",
    ),
    TuningParameter(
        "speed.walking_kmh",
        "押して歩く速度", "km/h", 4.5, 1.0, 10.0, TuningEffect.IMMEDIATE,
        "登りでこれ以下になったら押して歩くとみなす。",
    ),
    TuningParameter(
        "speed.climb_power_per_grade",
        "登りの出力の増え方", "W/%", 25.0, 0.0, 200.0,
        TuningEffect.IMMEDIATE,
        "勾配1%あたり何W余分に踏むか。勾配5%で時速10km前後という実感に"
        "合わせた暫定値で、根拠は薄い。",
    ),
    TuningParameter(
        "speed.max_climb_power_ratio",
        "登りの出力の上限倍率", "倍", 2.5, 1.0, 10.0,
        TuningEffect.IMMEDIATE,
        "平地の巡航に対して何倍まで踏むか。増え方をここで頭打ちにする。",
    ),
    # --- 主観と時間の換算 ---
    TuningParameter(
        "evaluation.penalty_strength",
        "主観と時間の換算レート", "", 0.7, 0.0, 5.0,
        TuningEffect.RESTART,
        "難易度を所要時間の割増しへ換算する強さ。"
        "リクエストごとに上書きできるため、ここで決めるのは省略されたときの値。",
    ),
)


#: 較正値ではない固定値（モジュール → 定数名 → 種別）。**値と根拠は使う側に置いたまま**で、
#: ここが持つのは分類だけ。キーの並びがそのまま検知器の対象範囲で、**定数が1つも無い
#: モジュールも空で挙げておく**——後から数値を1つ置いたときに拾われるようにするため。
FIXED_VALUES: dict[str, dict[str, FixedValueKind]] = {
    "app/domain/geo.py": {
        "EARTH_RADIUS_KM": FixedValueKind.PHYSICAL,
        "KM_PER_DEGREE_LATITUDE": FixedValueKind.PHYSICAL,
    },
    "app/domain/graph.py": {},
    "app/domain/routing.py": {
        "_HEAP_INITIAL_SLACK": FixedValueKind.NUMERICAL,
        "DEFAULT_NODE_INDEX_CELL_SIZE_DEG": FixedValueKind.NUMERICAL,
        "_NEIGHBOR_CELL_TOLERANCE": FixedValueKind.NUMERICAL,
    },
    "app/domain/route.py": {
        "SEGMENT_BIN_DISTANCE_KM": FixedValueKind.NUMERICAL,
    },
    "app/domain/cycling_speed.py": {
        "AIR_DENSITY_KG_M3": FixedValueKind.PHYSICAL,
        "GRAVITY_M_S2": FixedValueKind.PHYSICAL,
        "SPEED_SOLVE_ITERATIONS": FixedValueKind.NUMERICAL,
    },
    "app/domain/traffic.py": {
        "INTERSECTION_DEGREE_THRESHOLD": FixedValueKind.PRECOMPUTED,
        "POI_CLUSTER_EPS_M": FixedValueKind.PRECOMPUTED,
        "POI_ON_EDGE_TOLERANCE_M": FixedValueKind.PRECOMPUTED,
    },
    "app/domain/wind.py": {
        "ASSUMED_SPEED_KMH": FixedValueKind.EXTERNAL,
        "MIN_ASSUMED_SPEED_KMH": FixedValueKind.EXTERNAL,
        "MAX_ASSUMED_SPEED_KMH": FixedValueKind.EXTERNAL,
        "ROUTE_DETOUR_RATIO": FixedValueKind.NUMERICAL,
        "WIND_DRAG_REFERENCE_SPEED_MS": FixedValueKind.EXTERNAL,
    },
    "app/domain/evaluation.py": {},
    "app/services/road_graph_engine.py": {
        "BBOX_MARGIN_RATIO": FixedValueKind.NUMERICAL,
        "BBOX_MARGIN_MIN_KM": FixedValueKind.NUMERICAL,
        "PREVIEW_BBOX_MARGIN_KM": FixedValueKind.NUMERICAL,
        "RETRACE_PENALTY_MULTIPLIER": FixedValueKind.NUMERICAL,
        "MIN_TURNAROUND_SEPARATION_KM": FixedValueKind.NUMERICAL,
        "TURNAROUND_MAX_OVERLAP_RATIO": FixedValueKind.NUMERICAL,
        "TURNAROUND_RELAXED_OVERLAP_RATIO": FixedValueKind.NUMERICAL,
        "LOOP_MAX_OVERLAP_RATIO": FixedValueKind.NUMERICAL,
        "MAX_RING_CANDIDATES_EXAMINED": FixedValueKind.BUDGET,
        "LOOP_TO_OUTBOUND_RATIO_MIN": FixedValueKind.NUMERICAL,
        "LOOP_TO_OUTBOUND_RATIO_MAX": FixedValueKind.NUMERICAL,
        "COST_LIMIT_SLACK": FixedValueKind.NUMERICAL,
        "TIME_BIN_HOURS": FixedValueKind.EXTERNAL,
        "MAX_TIME_BINS": FixedValueKind.BUDGET,
        "PARETO_DISTANCE_QUANTUM_M": FixedValueKind.NUMERICAL,
        "PARETO_DIFFICULTY_QUANTUM": FixedValueKind.NUMERICAL,
        "ALTERNATIVE_MAX_STRETCH": FixedValueKind.NUMERICAL,
        "MAX_VIA_NODE_CANDIDATES_EXAMINED": FixedValueKind.BUDGET,
        "MAX_DESTINATION_CORRECTION_KM": FixedValueKind.NUMERICAL,
    },
    "app/services/route_generator.py": {
        "TURNAROUND_RADIUS_RATIO": FixedValueKind.NUMERICAL,
        "DEFAULT_MAX_ROUTES": FixedValueKind.BUDGET,
        "MAX_ROUTES": FixedValueKind.BUDGET,
        "TURNAROUND_POOL_FACTOR": FixedValueKind.BUDGET,
        "TURNAROUND_POOL_MIN": FixedValueKind.BUDGET,
        "TURNAROUND_POOL_MAX": FixedValueKind.BUDGET,
    },
    "app/services/evaluation_service.py": {},
}


#: 宣言の逆引き。
TUNING_PARAMETERS_BY_ID: dict[str, TuningParameter] = {p.id: p for p in TUNING_PARAMETERS}

#: いま効いている値（id → 値）。既定で初期化し、DBの上書きを読み込んだときに**中身だけ**を
#: 差し替える（束縛済みの参照先が古いままにならないよう、`.clear()`+`.update()`で更新する。
#: `services/axis_registry_service.py`が`AXIS_DEFINITIONS`へ採っているのと同じ流儀）。
TUNING_VALUES: dict[str, float] = {p.id: p.default for p in TUNING_PARAMETERS}


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
    "FIXED_VALUES",
    "TUNING_PARAMETERS",
    "TUNING_PARAMETERS_BY_ID",
    "TUNING_VALUES",
    "FixedValueKind",
    "TuningEffect",
    "TuningParameter",
    "stop_seconds_parameter_id",
    "tuning_value",
    "turn_parameter_ids",
]
