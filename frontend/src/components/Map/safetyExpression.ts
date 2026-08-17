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
// 出力は1〜4、または「判定対象外（highway未登録）」を表すセンチネル-1（recipeExpression.ts:
// UNKNOWN_LEVEL参照、trafficStressExpression.tsと同じ流儀）。
import type { SafetyRecipeOverride } from "@/types/route";
import defaultRecipeJson from "@/types/generated/safety-recipe.json";
import {
  baseByHighwayExpr,
  clampLevelExpr,
  buildRecipeLevelExpression,
  cyclewayAdjustmentExpr,
  designationAdjustmentExpr,
  evaluateRecipeLevel,
  flagAdjustmentExpr,
  thresholdAdjustmentExpr,
} from "@/components/Map/recipeExpression";

export type SafetyRecipe = SafetyRecipeOverride;

export const DEFAULT_SAFETY_RECIPE: SafetyRecipe = defaultRecipeJson;

export function buildSafetyExpression(recipe: SafetyRecipe): unknown[] {
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
  // 安全度はlanes_high（多車線＝リスク増）のみ採用する（domain/safety.py: SafetyRecipeの
  // docstring参照。少車線が安全側かは研究上見解が分かれるためlanes_lowは見送り）。
  // lowThreshold=nullでlow方向の補正を無効化する。
  const lanesAdjustment = thresholdAdjustmentExpr("lanes_count", null, 0, recipe.lanes_high_threshold, recipe.lanes_high_adjustment);
  const litAdjustment = flagAdjustmentExpr("lit", recipe.lit_adjustment);
  const tunnelAdjustment = flagAdjustmentExpr("tunnel", recipe.tunnel_adjustment);
  const designationAdjustment = designationAdjustmentExpr(recipe.designation_adjustment);

  const formula = clampLevelExpr(1, 4, [
    base,
    cyclewayAdjustment,
    maxspeedAdjustment,
    lanesAdjustment,
    litAdjustment,
    tunnelAdjustment,
    designationAdjustment,
  ]);
  return buildRecipeLevelExpression(hasBase, formula);
}

export function evaluateSafetyLevel(
  properties: Record<string, unknown>,
  recipe: SafetyRecipe = DEFAULT_SAFETY_RECIPE,
): number | null {
  return evaluateRecipeLevel(buildSafetyExpression(recipe), properties, "安全度");
}
