// 安全度（1-4、客観的な事故・怪我リスク）をタイルの材料タグ（backend/app/infrastructure/
// road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQLが焼き込むhighway/cycleway_class/
// maxspeed_kmh/lanes_count/designation/motor_vehicle_no/lit/tunnel）から
// ブラウザ側で計算するMapLibre expression。trafficStressExpression.tsと完全に同じ構造・
// 同じ理由（改善計画: 安全度レシピ。レシピを変えるたびにタイルキャッシュを作り直さずに
// 済ませるため、最終値の計算はここで行う）。
//
// backend/app/domain/safety.py: safety_breakdownと1:1対応させる（判定ロジックの正準は
// Python側。ここは同じレシピをMapLibre expressionとして再現するミラー）。補正ブロック生成
// 自体はtrafficStressExpression.tsと共有のrecipeExpression.ts（改善計画T123、
// domain/recipe.pyのTS側ミラー）に集約されている。既定レシピは
// types/generated/safety-recipe.json（export_openapi.pyがPython側のDEFAULT_SAFETY_RECIPEから
// 書き出す）から読み、手動同期を避ける（safetyExpression.test.tsがPython側との整合を検証する）。
//
// 「道路適正」「自動車密度」（=「車との近さ」N2）は交通ストレスと共有するレシピのため、
// 既定値はtypes/generated/road-suitability-recipe.json / motor-vehicle-density-recipe.jsonから
// 読む（改善計画: 車との近さ材料の共有元化）。
//
// 出力は1〜4、または「判定対象外（highway未登録）」を表すセンチネル-1（recipeExpression.ts:
// UNKNOWN_LEVEL参照、trafficStressExpression.tsと同じ流儀）。
import type {
  MotorVehicleDensityRecipeOverride,
  RoadSuitabilityRecipeOverride,
  SafetyRecipeOverride,
} from "@/types/route";
import defaultRecipeJson from "@/types/generated/safety-recipe.json";
import defaultRoadSuitabilityRecipeJson from "@/types/generated/road-suitability-recipe.json";
import defaultMotorVehicleDensityRecipeJson from "@/types/generated/motor-vehicle-density-recipe.json";
import {
  carClosenessExpr,
  clampLevelExpr,
  buildRecipeLevelExpression,
  evaluateRecipeLevel,
  flagAdjustmentExpr,
  type CarClosenessExpr,
} from "@/components/Map/recipeExpression";

export type SafetyRecipe = SafetyRecipeOverride;
export type RoadSuitabilityRecipe = RoadSuitabilityRecipeOverride;
export type MotorVehicleDensityRecipe = MotorVehicleDensityRecipeOverride;

export const DEFAULT_SAFETY_RECIPE: SafetyRecipe = defaultRecipeJson;
export const DEFAULT_ROAD_SUITABILITY_RECIPE: RoadSuitabilityRecipe = defaultRoadSuitabilityRecipeJson;
export const DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE: MotorVehicleDensityRecipe = defaultMotorVehicleDensityRecipeJson;

export function buildSafetyExpression(
  recipe: SafetyRecipe,
  roadSuitabilityRecipe: RoadSuitabilityRecipe = DEFAULT_ROAD_SUITABILITY_RECIPE,
  motorVehicleDensityRecipe: MotorVehicleDensityRecipe = DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  // 交通ストレスと共有する土台（改善計画: 車との近さ材料の共有元化）。同じ
  // roadSuitabilityRecipe/motorVehicleDensityRecipeに対してbuildTrafficStressExpressionも
  // 同じ結果を必要とするため、呼び出し側（MapView.tsx）が1回だけ計算した結果を
  // 渡せるようにする（省略時はここで計算する、既存呼び出し元との後方互換）。
  carCloseness: CarClosenessExpr = carClosenessExpr(roadSuitabilityRecipe, motorVehicleDensityRecipe),
): unknown[] {
  // 安全度はlanes_high（多車線＝リスク増）のみ採用する（domain/safety.py: SafetyRecipeの
  // docstring参照。少車線が安全側かは研究上見解が分かれるためlanes_lowは見送り、車との近さの
  // lanes_high側のみで足りる）。
  const { hasBase, base, cyclewayAdjustment, maxspeedAdjustment, lanesHighAdjustment, designationAdjustment } =
    carCloseness;
  const litAdjustment = flagAdjustmentExpr("lit", recipe.lit_adjustment);
  const tunnelAdjustment = flagAdjustmentExpr("tunnel", recipe.tunnel_adjustment);

  const formula = clampLevelExpr(1, 4, [
    base,
    cyclewayAdjustment,
    maxspeedAdjustment,
    lanesHighAdjustment,
    litAdjustment,
    tunnelAdjustment,
    designationAdjustment,
  ]);
  return buildRecipeLevelExpression(hasBase, formula);
}

export function evaluateSafetyLevel(
  properties: Record<string, unknown>,
  recipe: SafetyRecipe = DEFAULT_SAFETY_RECIPE,
  roadSuitabilityRecipe: RoadSuitabilityRecipe = DEFAULT_ROAD_SUITABILITY_RECIPE,
  motorVehicleDensityRecipe: MotorVehicleDensityRecipe = DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  carCloseness: CarClosenessExpr = carClosenessExpr(roadSuitabilityRecipe, motorVehicleDensityRecipe),
): number | null {
  return evaluateRecipeLevel(
    buildSafetyExpression(recipe, roadSuitabilityRecipe, motorVehicleDensityRecipe, carCloseness),
    properties,
    "安全度",
  );
}
