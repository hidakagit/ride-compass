"""安全度（客観的な事故・怪我リスク）の派生分類（改善計画: 安全度レシピ）。

交通ストレス（domain/traffic.py: traffic_stress_breakdown）は「走りにくさ・主観的な
快適性」を表す軸である一方、こちらは「事故りやすさ・客観的なリスク」を表す別概念として
ユーザーと合意のうえ新設した。material tags（highway/cycleway_class/maxspeed_kmh/
lanes_count/motor_vehicle_no/designation/lit/tunnel）からの変換式という構造・実装
パターンは交通ストレスと完全に共通で、採点構造そのもの（クランプ・閾値分岐・cycleway/
flag補正）は`domain/recipe.py`（改善計画T122）の共有プリミティブ経由。`SafetyRecipe`
という「レシピ」で外出しし、リクエスト単位で上書き可能、地図表示側は
`frontend/src/components/Map/safetyExpression.ts`が同じレシピをMapLibre expressionとして
再現する。

事故密度（警察庁統計）は意図的にこのレシピへ組み込まない。事故密度は特定のOSMタグから
決まる「材料」ではなく空間統計であり、既存の`accident_weight`軸（domain/difficulty.py）が
既にその役割を持つため、二重計上を避けて別軸のまま独立させる（ユーザー承認済み）。

shoulder（路肩）は当初material tagsに含めていたが、実測（改善計画T102: 街灯・分離歩道・
バリアタグのカバレッジ実測）で付与率0.0%（関東本土1,329,632way中0件）と判明した
「死に補正」だったため、T122で撤去した（YAMLのコメントに実測値を残し、地域拡大時の
復活判断材料とする）。
"""

from pydantic import BaseModel

from app.domain.recipe import (
    DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
    DEFAULT_ROAD_SUITABILITY_RECIPE,
    MotorVehicleDensityRecipe,
    RoadSuitabilityRecipe,
    car_closeness,
    clamp_level,
    cycleway_class,
    flag_adjustment,
    parse_lanes,
    parse_maxspeed,
    tag_value_is,
)


class SafetyRecipe(BaseModel):
    """`safety_breakdown`の判定基準のうち、安全度軸だけが持つ補正（街灯・トンネル）を
    まとめた「レシピ」。`domain/traffic.py: TrafficStressRecipe`と同じ構造・同じ切り出し
    方針（研究フェーズでのレシピ調整・将来の個人最適化に向けてリクエスト単位で上書き可能）。

    highway別基準値・cycleway補正・制限速度補正・車線数[多い方]補正・指定路線補正は
    「車との近さ」（N2）として交通ストレスと共有する（`domain/recipe.py:
    RoadSuitabilityRecipe`/`MotorVehicleDensityRecipe`/`car_closeness()`、改善計画:
    車との近さ材料の共有元化）ため、ここには含まない。少車線（lanes_low）が安全側に
    働くかは（対向車とのすれ違い頻度は減る一方、道幅自体が狭くなり接触余地が減る等）
    研究上見解が分かれるため、交通ストレス軸のみが持つ補正のままで安全度には採用しない
    （根拠のない補正を追加しないという方針を踏襲）。
    """

    lit_adjustment: int = -1
    tunnel_adjustment: int = 1


DEFAULT_SAFETY_RECIPE = SafetyRecipe()


class SafetyBreakdown(BaseModel):
    """`safety_level`の判定内訳（domain/traffic.py: TrafficStressBreakdownと同じ役割・
    同じ形）。地図上の道路クリック時に「なぜこの値になったか」を説明する表示専用データ。
    highwayが判定基準（`domain/recipe.py: ROAD_SUITABILITY_BASE_BY_HIGHWAY`）に
    登録されていない場合は`base`/`level`ともNoneで、他の補正フィールドは0/False。
    """

    base: int | None
    cycleway_adjustment: int
    maxspeed_adjustment: int
    lanes_adjustment: int
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
    road_suitability_recipe: RoadSuitabilityRecipe | None = None,
    motor_vehicle_density_recipe: MotorVehicleDensityRecipe | None = None,
) -> SafetyBreakdown:
    """安全度（1-4段階、1=安全〜4=危険）を、各補正の適用有無・量が分かる内訳付きで返す。
    構造は`domain/traffic.py: traffic_stress_breakdown`と同一（基本値はhighwayのみで決まり
    未知のhighwayはNone、補正はタグが実際にある場合のみ適用）。

    `recipe`省略時は`DEFAULT_SAFETY_RECIPE`を使う。`road_suitability_recipe`/
    `motor_vehicle_density_recipe`は省略時それぞれ`DEFAULT_ROAD_SUITABILITY_RECIPE`/
    `DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE`（改善計画: 車との近さ材料の共有元化。
    この2つは交通ストレス側と共有する「車との近さ」(N2)の材料で、`recipe`
    [`SafetyRecipe`]はこの軸固有の街灯・トンネル補正のみを持つ）。cycleway系タグの分類は
    `cycleway_class`（domain/recipe.py、交通ストレスと共有）を再利用する。

    `is_designated`はKSJ N10/N12該当（domain/designation.py）で、大型車混入の代理指標
    として交通ストレスと同じ意味・同じ+1既定値で扱う。
    """
    recipe = recipe or DEFAULT_SAFETY_RECIPE
    road_suitability_recipe = road_suitability_recipe or DEFAULT_ROAD_SUITABILITY_RECIPE
    motor_vehicle_density_recipe = motor_vehicle_density_recipe or DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE

    # 改善計画: 車との近さ材料の共有元化。「道路適正＋自動車密度」（N2、交通ストレス側
    # domain/traffic.py: traffic_stress_breakdownと共有）はdomain/recipe.py:
    # car_closeness()へ切り出し済み。
    base, cycleway_adj, maxspeed_adj, lanes_adj, designation_adj = car_closeness(
        highway, tags, is_designated, road_suitability_recipe, motor_vehicle_density_recipe
    )
    if base is None:
        return SafetyBreakdown(
            base=None,
            cycleway_adjustment=0,
            maxspeed_adjustment=0,
            lanes_adjustment=0,
            lit_adjustment=0,
            tunnel_adjustment=0,
            designation_adjustment=0,
            motor_vehicle_no_override=False,
            level=None,
        )

    # motor_vehicle=no（自転車可）は他の補正に関わらず最も安全な1に固定
    # （traffic_stress_breakdownと同じ扱い。車が入れない道は事故リスクが最小）。
    if tag_value_is(tags, "motor_vehicle", "no"):
        return SafetyBreakdown(
            base=base,
            cycleway_adjustment=0,
            maxspeed_adjustment=0,
            lanes_adjustment=0,
            lit_adjustment=0,
            tunnel_adjustment=0,
            designation_adjustment=0,
            motor_vehicle_no_override=True,
            level=1,
        )

    # 安全度はlanes_high（多車線＝リスク増、car_closeness()由来）のみ採用する
    # （少車線が安全側かは研究上見解が分かれるため見送り、SafetyRecipeのdocstring参照）。
    lit_adj = flag_adjustment(tag_value_is(tags, "lit", "yes"), recipe.lit_adjustment)
    tunnel_adj = flag_adjustment(tag_value_is(tags, "tunnel", "yes"), recipe.tunnel_adjustment)

    level = clamp_level(base + cycleway_adj + maxspeed_adj + lanes_adj + lit_adj + tunnel_adj + designation_adj, 1, 4)

    return SafetyBreakdown(
        base=base,
        cycleway_adjustment=cycleway_adj,
        maxspeed_adjustment=maxspeed_adj,
        lanes_adjustment=lanes_adj,
        lit_adjustment=lit_adj,
        tunnel_adjustment=tunnel_adj,
        designation_adjustment=designation_adj,
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
    if tag_value_is(tags, "motor_vehicle", "no"):
        ingredients["motor_vehicle_no"] = True
    if tag_value_is(tags, "lit", "yes"):
        ingredients["lit"] = True
    if tag_value_is(tags, "tunnel", "yes"):
        ingredients["tunnel"] = True
    if is_designated:
        ingredients["designation"] = "emergency_transport"
    return ingredients


def safety_level(
    highway: str | None,
    tags: dict[str, str],
    is_designated: bool = False,
    recipe: SafetyRecipe | None = None,
    road_suitability_recipe: RoadSuitabilityRecipe | None = None,
    motor_vehicle_density_recipe: MotorVehicleDensityRecipe | None = None,
) -> int | None:
    """安全度（1-4段階）の最終値のみを返す薄いラッパー。判定ロジック・docstringは
    `safety_breakdown`参照。"""
    return safety_breakdown(
        highway, tags, is_designated, recipe, road_suitability_recipe, motor_vehicle_density_recipe
    ).level
