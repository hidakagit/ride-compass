"""レシピのデータ定義（改善計画T141、設計プロンプト「レシピのデータ定義」節）。

recipe_id + versionで識別できる、宣言的なレシピ（〇次フィルタ・軸内係数・三次重み）を
1つのPydanticモデル`Recipe`として表現する。研究モードのスロット比較（`ExperimentSlot`）を
将来「差分レイヤー」へ発展させる前提のため、レシピをID+versionで保持できる構造にする。

**現時点ではAPI層・OpenAPI契約・フロントへは配線しない**（`domain/registry.py`（T137）と
同じ「宣言のみ」の非破壊的な追加）。既存の4YAML＋Pydanticモデル（`RoutePreference`/
`CarStressRecipe`/`RoadSuitabilityRecipe`/`MotorVehicleDensityRecipe`、それぞれ
`compute_edge_cost`等の実処理から直接読まれる「唯一の実体」。当初は`SafetyRecipe`も
含む5つだったが、安全度軸はT148で削除済み）は変更せず残し、
本モジュールは2方向の変換層として機能する（設計プロンプトが許容する「既存YAML群を
axis_params/weightsのキーへマッピングして読み込む後方互換レイヤー」の実装）:

- `recipe_from_components()`: 既存の型付きモデル群 → `Recipe`（表示・保存・比較用）
- `recipe_to_components()`: `Recipe` → 既存の型付きモデル群（`compute_edge_cost`等へそのまま渡せる）

実際の配線（API層がRecipeを受け取る・地図表示とコスト計算が同一Recipeから生成される）は
T142（コスト関数の縮退）以降で行う。

`axis_params`のキーは軸内レシピ名（`road_suitability`/`motor_vehicle_density`/
`car_stress`）。設計プロンプトが示す目標のaxis_id（`car_stress`等）へは
改善計画T150（呼称統一）で追従済み（旧`traffic_stress`から改称）。`safety`は
T139で難易度合成からは外れ、T148で`domain/safety.py`自体も削除されたため
`axis_params`から除いた。`gradient`/`surface_q`/`stop_density`
（改善計画T149で交差点密度を吸収済み）/`accident`/`night`は現状オーバーライド可能な
「レシピ」を持たない（`domain/difficulty.py`/`domain/night.py`のモジュール定数のみ、
研究モードでの上書き対象外）ため`axis_params`には含めない。
"""

from typing import NamedTuple

from pydantic import BaseModel

from app.domain.evaluation import DEFAULT_HARD_FILTERS, RoutePreference
from app.domain.recipe import (
    DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
    DEFAULT_ROAD_SUITABILITY_RECIPE,
    MotorVehicleDensityRecipe,
    RoadSuitabilityRecipe,
)
from app.domain.traffic import DEFAULT_CAR_STRESS_RECIPE, CarStressRecipe

# axis_paramsのキー名（軸内レシピ名。car_stressはT150でtraffic_stressから改称済み）。
AXIS_PARAM_ROAD_SUITABILITY = "road_suitability"
AXIS_PARAM_MOTOR_VEHICLE_DENSITY = "motor_vehicle_density"
AXIS_PARAM_CAR_STRESS = "car_stress"


class Recipe(BaseModel):
    """〇次フィルタ・軸内係数・三次重みを1つのJSON互換構造にまとめた宣言的なレシピ。

    `hard_filters`は`domain/evaluation.py: is_edge_allowed`の`hard_filters`引数へ
    そのまま渡せるフィルタ名のリスト（`{"no_bicycle", "motorway", "trunk"}`の部分集合）。
    `axis_params`は軸内係数（事実の較正、全レシピ共通が原則だが研究モードでは編集可）、
    `weights`は三次重み（好みの表明、レシピ/スロットごとに可変）。両者を1つのモデルで
    混在させない設計上の区別は維持する（`axis_params`のキーはモジュールdocstring参照）。
    """

    recipe_id: str
    version: int
    hard_filters: list[str]
    axis_params: dict[str, dict[str, object]]
    weights: dict[str, float]


class RecipeComponents(NamedTuple):
    """`Recipe`から取り出した、既存の実処理がそのまま受け取れる型付きモデル群。"""

    preference: RoutePreference
    car_stress_recipe: CarStressRecipe
    road_suitability_recipe: RoadSuitabilityRecipe
    motor_vehicle_density_recipe: MotorVehicleDensityRecipe
    hard_filters: frozenset[str]


def recipe_from_components(
    recipe_id: str,
    version: int,
    preference: RoutePreference,
    car_stress_recipe: CarStressRecipe,
    road_suitability_recipe: RoadSuitabilityRecipe,
    motor_vehicle_density_recipe: MotorVehicleDensityRecipe,
    hard_filters: frozenset[str] = DEFAULT_HARD_FILTERS,
) -> Recipe:
    """既存の型付きモデル群から`Recipe`を組み立てる（表示・保存・比較用の射影）。"""
    return Recipe(
        recipe_id=recipe_id,
        version=version,
        hard_filters=sorted(hard_filters),
        axis_params={
            AXIS_PARAM_ROAD_SUITABILITY: road_suitability_recipe.model_dump(),
            AXIS_PARAM_MOTOR_VEHICLE_DENSITY: motor_vehicle_density_recipe.model_dump(),
            AXIS_PARAM_CAR_STRESS: car_stress_recipe.model_dump(),
        },
        weights=preference.model_dump(),
    )


def recipe_to_components(recipe: Recipe) -> RecipeComponents:
    """`Recipe`から、既存の実処理（`compute_edge_cost`等）へそのまま渡せる型付きモデル群を
    取り出す。`axis_params`に該当キーが無い場合はその軸のクラス既定値を使う（部分的な
    レシピJSON、たとえば`weights`のみ指定して`axis_params`を省略する使い方を許容する）。
    """
    axis_params = recipe.axis_params
    return RecipeComponents(
        preference=RoutePreference(**recipe.weights),
        car_stress_recipe=CarStressRecipe(**axis_params.get(AXIS_PARAM_CAR_STRESS, {})),
        road_suitability_recipe=RoadSuitabilityRecipe(**axis_params.get(AXIS_PARAM_ROAD_SUITABILITY, {})),
        motor_vehicle_density_recipe=MotorVehicleDensityRecipe(
            **axis_params.get(AXIS_PARAM_MOTOR_VEHICLE_DENSITY, {})
        ),
        hard_filters=frozenset(recipe.hard_filters),
    )


def default_recipe(recipe_id: str = "default", version: int = 1) -> Recipe:
    """既定のクラス値（`route_preference.yaml`等のYAML既定値と同値のPydanticクラス既定値）
    から組み立てた`Recipe`。YAML自体は読まない（呼び出し元がリクエスト単位でYAML由来の
    既定値を渡したい場合は`recipe_from_components`を直接使う。テスト・簡易確認用の
    ショートカット）。
    """
    return recipe_from_components(
        recipe_id,
        version,
        RoutePreference(),
        DEFAULT_CAR_STRESS_RECIPE,
        DEFAULT_ROAD_SUITABILITY_RECIPE,
        DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
    )
