// 交通ストレス（1-5）をタイルの材料タグ（backend/app/infrastructure/road_graph_repository.py:
// _ROAD_SURFACE_TILE_MVT_SQLが焼き込むhighway/cycleway_class/maxspeed_kmh/lanes_count/
// designation/motor_vehicle_no）からブラウザ側で計算するMapLibre expression。
//
// 改善計画（交通ストレスレシピ外出し基盤）: 以前はSQL側で最終値を計算しタイル（全ユーザー
// 共有・キャッシュ）へ焼き込んでいたが、レシピ（highway別基準値・各補正の閾値・補正量）を
// 変えるたびに世界中のタイルキャッシュを作り直す必要があった。材料タグだけをタイルへ残し、
// 最終値の計算をここへ移すことで、レシピの変更が地図表示に関してサーバー・キャッシュに
// 一切触れず完結する。
//
// backend/app/domain/traffic.py: traffic_stress_breakdownと1:1対応させる（判定ロジックの
// 正準はPython側。ここは同じレシピをMapLibre expressionとして再現するミラー）。補正ブロック
// 生成自体はsafetyExpression.tsと共有のrecipeExpression.ts（改善計画T123、domain/recipe.pyの
// TS側ミラー）に集約されている。既定レシピはtypes/generated/traffic-stress-recipe.json
// （export_openapi.pyがPython側のDEFAULT_TRAFFIC_STRESS_RECIPEから書き出す）から読み、
// 手動同期を避ける（trafficStressExpression.test.tsがPython側との整合を検証する）。
//
// 「道路適正」「自動車密度」（=「車との近さ」N2）は安全度と共有するレシピのため、既定値は
// types/generated/road-suitability-recipe.json / motor-vehicle-density-recipe.jsonから読む
// （改善計画: 車との近さ材料の共有元化）。
//
// 出力は1〜5、または「判定対象外（highway未登録）」を表すセンチネル-1（recipeExpression.ts:
// UNKNOWN_LEVEL参照）。
import type {
  MotorVehicleDensityRecipeOverride,
  RoadSuitabilityRecipeOverride,
  TrafficStressRecipeOverride,
} from "@/types/route";
import defaultRecipeJson from "@/types/generated/traffic-stress-recipe.json";
import defaultRoadSuitabilityRecipeJson from "@/types/generated/road-suitability-recipe.json";
import defaultMotorVehicleDensityRecipeJson from "@/types/generated/motor-vehicle-density-recipe.json";
import {
  carClosenessExpr,
  clampLevelExpr,
  buildRecipeLevelExpression,
  evaluateRecipeLevel,
  thresholdAdjustmentExpr,
  type CarClosenessExpr,
} from "@/components/Map/recipeExpression";

export type TrafficStressRecipe = TrafficStressRecipeOverride;
export type RoadSuitabilityRecipe = RoadSuitabilityRecipeOverride;
export type MotorVehicleDensityRecipe = MotorVehicleDensityRecipeOverride;

export const DEFAULT_TRAFFIC_STRESS_RECIPE: TrafficStressRecipe = defaultRecipeJson;
export const DEFAULT_ROAD_SUITABILITY_RECIPE: RoadSuitabilityRecipe = defaultRoadSuitabilityRecipeJson;
export const DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE: MotorVehicleDensityRecipe = defaultMotorVehicleDensityRecipeJson;

export function buildTrafficStressExpression(
  recipe: TrafficStressRecipe,
  roadSuitabilityRecipe: RoadSuitabilityRecipe = DEFAULT_ROAD_SUITABILITY_RECIPE,
  motorVehicleDensityRecipe: MotorVehicleDensityRecipe = DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  // 「車との近さ」(N2 = 道路適正＋自動車密度、domain/recipe.py: car_closeness)。
  // 交通ストレス・安全度が共有する土台（改善計画: 車との近さ材料の共有元化）。同じ
  // roadSuitabilityRecipe/motorVehicleDensityRecipeに対してbuildSafetyExpressionも
  // 同じ結果を必要とするため、呼び出し側（MapView.tsx）が1回だけ計算した結果を
  // 渡せるようにする（省略時はここで計算する、既存呼び出し元との後方互換）。
  carCloseness: CarClosenessExpr = carClosenessExpr(roadSuitabilityRecipe, motorVehicleDensityRecipe),
): unknown[] {
  const { hasBase, base, cyclewayAdjustment, maxspeedAdjustment, lanesHighAdjustment, designationAdjustment } =
    carCloseness;

  // lanes_low(すれ違いの圧迫度緩和)は分離自転車道(cycleway_class=="track")区間では
  // 該当しない（domain/traffic.py: traffic_stress_breakdownと1:1対応）。lanes_high
  // （自動車密度レシピ由来）とは別レシピの値のため、1回のthreshold_adjustment呼び出しでは
  // 表現できず独立に計算して加算する（同domain関数のコメント参照）。
  const cyclewayIsTrack = ["==", ["coalesce", ["get", "cycleway_class"], ""], "track"];
  const lanesLowAdjustment = thresholdAdjustmentExpr(
    "lanes_count",
    recipe.lanes_low_threshold,
    recipe.lanes_low_adjustment,
    null,
    0,
    cyclewayIsTrack,
  );
  const lanesAdjustment = ["+", lanesHighAdjustment, lanesLowAdjustment];

  const formula = clampLevelExpr(1, 5, [base, cyclewayAdjustment, maxspeedAdjustment, lanesAdjustment, designationAdjustment]);
  return buildRecipeLevelExpression(hasBase, formula);
}

export function evaluateTrafficStressLevel(
  properties: Record<string, unknown>,
  recipe: TrafficStressRecipe = DEFAULT_TRAFFIC_STRESS_RECIPE,
  roadSuitabilityRecipe: RoadSuitabilityRecipe = DEFAULT_ROAD_SUITABILITY_RECIPE,
  motorVehicleDensityRecipe: MotorVehicleDensityRecipe = DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  carCloseness: CarClosenessExpr = carClosenessExpr(roadSuitabilityRecipe, motorVehicleDensityRecipe),
): number | null {
  return evaluateRecipeLevel(
    buildTrafficStressExpression(recipe, roadSuitabilityRecipe, motorVehicleDensityRecipe, carCloseness),
    properties,
    "車の圧迫感",
  );
}
