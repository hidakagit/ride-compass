"""安全度（客観的な事故・怪我リスク）の派生分類（改善計画: 安全度レシピ）。

交通ストレス（domain/traffic.py: traffic_stress_breakdown）は「走りにくさ・主観的な
快適性」を表す軸である一方、こちらは「事故りやすさ・客観的なリスク」を表す別概念として
ユーザーと合意のうえ新設した。material tags（highway/cycleway_class/maxspeed_kmh/
lanes_count/motor_vehicle_no/designation/shoulder/lit/tunnel）からの変換式という
構造・実装パターンは交通ストレスと完全に共通（`SafetyRecipe`という「レシピ」で外出しし、
リクエスト単位で上書き可能、地図表示側は`frontend/src/components/Map/safetyExpression.ts`が
同じレシピをMapLibre expressionとして再現する）。

事故密度（警察庁統計）は意図的にこのレシピへ組み込まない。事故密度は特定のOSMタグから
決まる「材料」ではなく空間統計であり、既存の`accident_weight`軸（domain/difficulty.py）が
既にその役割を持つため、二重計上を避けて別軸のまま独立させる（ユーザー承認済み）。
"""

from pydantic import BaseModel, Field

from app.domain.traffic import cycleway_class, parse_lanes, parse_maxspeed

# 安全度基準値（highwayのみで決定）。交通ストレスのTRAFFIC_STRESS_BASE_BY_HIGHWAYと
# 同じhighway集合（他の2軸とカバレッジを揃えない、というdomain/traffic.pyの方針を踏襲し
# 意図的に同一のキー集合を使う）だが、数値セットは別物（快適性と安全性は異なる概念のため、
# 値を共有すると「安全度を調整したつもりが交通ストレスも変わる」事故を招く）。
# 本格チューニングはP2据え置き（暫定値、TRAFFIC_STRESS_BASE_BY_HIGHWAYと同じ方針）。
SAFETY_BASE_BY_HIGHWAY: dict[str, int] = {
    "cycleway": 1,
    "living_street": 1,
    "residential": 2,
    "unclassified": 2,
    "track": 2,
    "tertiary": 2,
    "tertiary_link": 2,
    "secondary": 3,
    "secondary_link": 3,
    "primary": 4,
    "primary_link": 4,
    "trunk": 4,
    "trunk_link": 4,
}


class SafetyRecipe(BaseModel):
    """`safety_breakdown`の判定基準（highway別基準値＋各補正の閾値・補正量）をまとめた
    「レシピ」。`domain/traffic.py: TrafficStressRecipe`と同じ構造・同じ切り出し方針
    （研究フェーズでのレシピ調整・将来の個人最適化に向けてリクエスト単位で上書き可能）。

    lanesはlanes_high（多車線＝リスク増）のみを採用する。少車線が安全側に働くかは
    （対向車とのすれ違い頻度は減る一方、道幅自体が狭くなり接触余地が減る等）研究上
    見解が分かれるため、根拠のない補正を追加しないという方針（交通ストレスと同様、
    不確かな推測でNone以外を返さない）を踏襲しlanes_lowは見送る。
    """

    base_by_highway: dict[str, int] = Field(default_factory=lambda: dict(SAFETY_BASE_BY_HIGHWAY))
    cycleway_track_adjustment: int = -2
    cycleway_lane_adjustment: int = -1
    cycleway_shared_adjustment: int = -1
    maxspeed_low_threshold: int = 30
    maxspeed_low_adjustment: int = -1
    maxspeed_high_threshold: int = 60
    maxspeed_high_adjustment: int = 1
    lanes_high_threshold: int = 4
    lanes_high_adjustment: int = 1
    shoulder_adjustment: int = -1
    lit_adjustment: int = -1
    tunnel_adjustment: int = 1
    designation_adjustment: int = 1


DEFAULT_SAFETY_RECIPE = SafetyRecipe()


class SafetyBreakdown(BaseModel):
    """`safety_level`の判定内訳（domain/traffic.py: TrafficStressBreakdownと同じ役割・
    同じ形）。地図上の道路クリック時に「なぜこの値になったか」を説明する表示専用データ。
    highwayが判定基準（`SAFETY_BASE_BY_HIGHWAY`）に登録されていない場合は`base`/`level`
    ともNoneで、他の補正フィールドは0/False。
    """

    base: int | None
    cycleway_adjustment: int
    maxspeed_adjustment: int
    lanes_adjustment: int
    shoulder_adjustment: int
    lit_adjustment: int
    tunnel_adjustment: int
    designation_adjustment: int
    motor_vehicle_no_override: bool
    level: int | None


def safety_breakdown(
    highway: str | None,
    tags: dict[str, str],
    is_designated: bool = False,
    recipe: SafetyRecipe | None = None,
) -> SafetyBreakdown:
    """安全度（1-4段階、1=安全〜4=危険）を、各補正の適用有無・量が分かる内訳付きで返す。
    構造は`domain/traffic.py: traffic_stress_breakdown`と同一（基本値はhighwayのみで決まり
    未知のhighwayはNone、補正はタグが実際にある場合のみ適用）。

    `recipe`省略時は`DEFAULT_SAFETY_RECIPE`を使う。cycleway系タグの分類は
    `cycleway_class`（domain/traffic.py、交通ストレスと共有）を再利用する。

    `is_designated`はKSJ N10/N12該当（domain/designation.py）で、大型車混入の代理指標
    として交通ストレスと同じ意味・同じ+1既定値で扱う。
    """
    recipe = recipe or DEFAULT_SAFETY_RECIPE
    base = recipe.base_by_highway.get(highway or "")
    if base is None:
        return SafetyBreakdown(
            base=None,
            cycleway_adjustment=0,
            maxspeed_adjustment=0,
            lanes_adjustment=0,
            shoulder_adjustment=0,
            lit_adjustment=0,
            tunnel_adjustment=0,
            designation_adjustment=0,
            motor_vehicle_no_override=False,
            level=None,
        )

    # motor_vehicle=no（自転車可）は他の補正に関わらず最も安全な1に固定
    # （traffic_stress_breakdownと同じ扱い。車が入れない道は事故リスクが最小）。
    if (tags.get("motor_vehicle") or "").strip().lower() == "no":
        return SafetyBreakdown(
            base=base,
            cycleway_adjustment=0,
            maxspeed_adjustment=0,
            lanes_adjustment=0,
            shoulder_adjustment=0,
            lit_adjustment=0,
            tunnel_adjustment=0,
            designation_adjustment=0,
            motor_vehicle_no_override=True,
            level=1,
        )

    cycleway = cycleway_class(tags)
    if cycleway == "track":
        cycleway_adjustment = recipe.cycleway_track_adjustment
    elif cycleway == "lane":
        cycleway_adjustment = recipe.cycleway_lane_adjustment
    elif cycleway == "shared":
        cycleway_adjustment = recipe.cycleway_shared_adjustment
    else:
        cycleway_adjustment = 0

    maxspeed = parse_maxspeed(tags)
    if maxspeed is not None and maxspeed <= recipe.maxspeed_low_threshold:
        maxspeed_adjustment = recipe.maxspeed_low_adjustment
    elif maxspeed is not None and maxspeed >= recipe.maxspeed_high_threshold:
        maxspeed_adjustment = recipe.maxspeed_high_adjustment
    else:
        maxspeed_adjustment = 0

    lanes = parse_lanes(tags)
    if lanes is not None and lanes >= recipe.lanes_high_threshold:
        lanes_adjustment = recipe.lanes_high_adjustment
    else:
        lanes_adjustment = 0

    shoulder_adjustment = recipe.shoulder_adjustment if (tags.get("shoulder") or "").strip().lower() == "yes" else 0
    lit_adjustment = recipe.lit_adjustment if (tags.get("lit") or "").strip().lower() == "yes" else 0
    tunnel_adjustment = recipe.tunnel_adjustment if (tags.get("tunnel") or "").strip().lower() == "yes" else 0
    designation_adjustment = recipe.designation_adjustment if is_designated else 0

    level = max(
        1,
        min(
            4,
            base
            + cycleway_adjustment
            + maxspeed_adjustment
            + lanes_adjustment
            + shoulder_adjustment
            + lit_adjustment
            + tunnel_adjustment
            + designation_adjustment,
        ),
    )

    return SafetyBreakdown(
        base=base,
        cycleway_adjustment=cycleway_adjustment,
        maxspeed_adjustment=maxspeed_adjustment,
        lanes_adjustment=lanes_adjustment,
        shoulder_adjustment=shoulder_adjustment,
        lit_adjustment=lit_adjustment,
        tunnel_adjustment=tunnel_adjustment,
        designation_adjustment=designation_adjustment,
        motor_vehicle_no_override=False,
        level=level,
    )


def safety_tile_ingredients(highway: str | None, tags: dict[str, str], is_designated: bool = False) -> dict[str, object]:
    """安全度の材料タグを、road-surface-tilesのMVTが実際に焼き込むプロパティと同じ形
    （キー名・値の有無）で返す。`export_openapi.py`が書き出す相互検証フィクスチャ
    （safety-test-cases.json、フロントのsafetyExpression.test.tsが読む）専用
    （domain/traffic.py: traffic_stress_tile_ingredientsと同じ役割）。
    """
    ingredients: dict[str, object] = {}
    if highway is not None:
        ingredients["highway"] = highway
    cycleway = cycleway_class(tags)
    if cycleway is not None:
        ingredients["cycleway_class"] = cycleway
    maxspeed = parse_maxspeed(tags)
    if maxspeed is not None:
        ingredients["maxspeed_kmh"] = maxspeed
    lanes = parse_lanes(tags)
    if lanes is not None:
        ingredients["lanes_count"] = lanes
    if (tags.get("motor_vehicle") or "").strip().lower() == "no":
        ingredients["motor_vehicle_no"] = True
    if (tags.get("shoulder") or "").strip().lower() == "yes":
        ingredients["shoulder"] = True
    if (tags.get("lit") or "").strip().lower() == "yes":
        ingredients["lit"] = True
    if (tags.get("tunnel") or "").strip().lower() == "yes":
        ingredients["tunnel"] = True
    if is_designated:
        ingredients["designation"] = "emergency_transport"
    return ingredients


def safety_level(
    highway: str | None,
    tags: dict[str, str],
    is_designated: bool = False,
    recipe: SafetyRecipe | None = None,
) -> int | None:
    """安全度（1-4段階）の最終値のみを返す薄いラッパー。判定ロジック・docstringは
    `safety_breakdown`参照。"""
    return safety_breakdown(highway, tags, is_designated, recipe).level
