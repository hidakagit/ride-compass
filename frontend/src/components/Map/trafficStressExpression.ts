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
// 出力は1〜5、または「判定対象外（highway未登録）」を表すセンチネル-1（recipeExpression.ts:
// UNKNOWN_LEVEL参照）。
import type { TrafficStressRecipeOverride } from "@/types/route";
import defaultRecipeJson from "@/types/generated/traffic-stress-recipe.json";
import {
  baseByHighwayExpr,
  clampLevelExpr,
  buildRecipeLevelExpression,
  cyclewayAdjustmentExpr,
  designationAdjustmentExpr,
  evaluateRecipeLevel,
  thresholdAdjustmentExpr,
} from "@/components/Map/recipeExpression";

export type TrafficStressRecipe = TrafficStressRecipeOverride;

export const DEFAULT_TRAFFIC_STRESS_RECIPE: TrafficStressRecipe = defaultRecipeJson;

export function buildTrafficStressExpression(recipe: TrafficStressRecipe): unknown[] {
  const { hasBase, base } = baseByHighwayExpr(recipe.base_by_highway);

  const cyclewayAdjustment = cyclewayAdjustmentExpr(
    recipe.cycleway_track_adjustment,
    recipe.cycleway_lane_adjustment,
    recipe.cycleway_shared_adjustment,
  );
  const maxspeedAdjustment = thresholdAdjustmentExpr(
    "maxspeed_kmh",
    recipe.maxspeed_low_threshold,
    recipe.maxspeed_low_adjustment,
    recipe.maxspeed_high_threshold,
    recipe.maxspeed_high_adjustment,
  );
  const lanesAdjustment = thresholdAdjustmentExpr(
    "lanes_count",
    recipe.lanes_low_threshold,
    recipe.lanes_low_adjustment,
    recipe.lanes_high_threshold,
    recipe.lanes_high_adjustment,
  );
  const designationAdjustment = designationAdjustmentExpr(recipe.designation_adjustment);

  const formula = clampLevelExpr(1, 5, [base, cyclewayAdjustment, maxspeedAdjustment, lanesAdjustment, designationAdjustment]);
  return buildRecipeLevelExpression(hasBase, formula);
}

export function evaluateTrafficStressLevel(
  properties: Record<string, unknown>,
  recipe: TrafficStressRecipe = DEFAULT_TRAFFIC_STRESS_RECIPE,
): number | null {
  return evaluateRecipeLevel(buildTrafficStressExpression(recipe), properties, "交通ストレス");
}
