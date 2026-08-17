// 安全度（1-4、客観的な事故・怪我リスク）をタイルの材料タグ（backend/app/infrastructure/
// road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQLが焼き込むhighway/cycleway_class/
// maxspeed_kmh/lanes_count/designation/motor_vehicle_no/lit/tunnel）から
// ブラウザ側で計算するMapLibre expression。trafficStressExpression.tsと完全に同じ構造・
// 同じ理由（改善計画: 安全度レシピ。レシピを変えるたびにタイルキャッシュを作り直さずに
// 済ませるため、最終値の計算はここで行う）。
//
// backend/app/domain/safety.py: safety_breakdownと1:1対応させる（判定ロジックの正準は
// Python側。ここは同じレシピをMapLibre expressionとして再現するミラー）。既定レシピは
// types/generated/safety-recipe.json（export_openapi.pyがPython側のDEFAULT_SAFETY_RECIPEから
// 書き出す）から読み、手動同期を避ける（safetyExpression.test.tsがPython側との整合を検証する）。
//
// 出力は1〜4、または「判定対象外（highway未登録）」を表すセンチネル-1（trafficStressExpression.ts
// と同じ流儀）。
//
// maplibre-gl本体とnode_modulesの@maplibre/maplibre-gl-style-specのバージョンずれに関する
// 注意はtrafficStressExpression.tsのコメント参照（同じ制約が適用される）。
import { createExpression } from "@maplibre/maplibre-gl-style-spec";
import type { SafetyRecipeOverride } from "@/types/route";
import defaultRecipeJson from "@/types/generated/safety-recipe.json";

export type SafetyRecipe = SafetyRecipeOverride;

export const DEFAULT_SAFETY_RECIPE: SafetyRecipe = defaultRecipeJson;

// 判定対象外（highway未登録、safety_breakdownのbase=Noneに対応）を表す出力センチネル。
// trafficStressExpression.tsのUNKNOWN_LEVELと同じ値・同じ意味。
const UNKNOWN_LEVEL = -1;

export function buildSafetyExpression(recipe: SafetyRecipe): unknown[] {
  const baseEntries = Object.entries(recipe.base_by_highway).flatMap(([highway, base]) => [highway, base]);
  const highwayKeys = Object.keys(recipe.base_by_highway);

  // highwayがbase_by_highwayに登録されているか（登録が無ければ判定対象外、safety_breakdownの
  // base=Noneに対応）。この判定でUNKNOWN_LEVELへ分岐させるため、以下のbase/formulaは
  // hasBaseがtrueの場合しか評価されない（case式の短絡評価）。matchのfallback値は到達しない
  // ため任意の数値でよい。
  const hasBase = ["in", ["get", "highway"], ["literal", highwayKeys]];
  const base = ["match", ["get", "highway"], ...baseEntries, 0];

  // cycleway_classは_ROAD_SURFACE_TILE_MVT_SQLが'track'|'lane'|'shared'|(キー無し)で焼く
  // （交通ストレスと共有の材料タグ、domain/traffic.py: cycleway_class）。
  const cyclewayAdjustment = [
    "match",
    ["coalesce", ["get", "cycleway_class"], ""],
    "track",
    recipe.cycleway_track_adjustment,
    "lane",
    recipe.cycleway_lane_adjustment,
    "shared",
    recipe.cycleway_shared_adjustment,
    0,
  ];

  // "has"で先にプロパティの有無を確認してから比較する（all/caseは短絡評価のため、
  // プロパティが無い場合に["<=", ["get",...], N]がnullと数値を比較してエラーになるのを防ぐ）。
  const maxspeedAdjustment = [
    "case",
    ["all", ["has", "maxspeed_kmh"], ["<=", ["get", "maxspeed_kmh"], recipe.maxspeed_low_threshold]],
    recipe.maxspeed_low_adjustment,
    ["all", ["has", "maxspeed_kmh"], [">=", ["get", "maxspeed_kmh"], recipe.maxspeed_high_threshold]],
    recipe.maxspeed_high_adjustment,
    0,
  ];

  // 安全度はlanes_high（多車線＝リスク増）のみ採用する（domain/safety.py: SafetyRecipeの
  // docstring参照。少車線が安全側かは研究上見解が分かれるためlanes_lowは見送り）。
  const lanesAdjustment = [
    "case",
    ["all", ["has", "lanes_count"], [">=", ["get", "lanes_count"], recipe.lanes_high_threshold]],
    recipe.lanes_high_adjustment,
    0,
  ];

  // lit/tunnelは真偽値の材料タグ（無ければキー自体が無い＝coalesceでfalse扱い）。
  const litAdjustment = ["case", ["==", ["coalesce", ["get", "lit"], false], true], recipe.lit_adjustment, 0];
  const tunnelAdjustment = ["case", ["==", ["coalesce", ["get", "tunnel"], false], true], recipe.tunnel_adjustment, 0];

  // designationは'emergency_transport'|'critical_logistics'|'both'|(キー無し)。値の種類を
  // 問わず「該当するかどうか」だけが安全度への補正条件（domain/safety.py: safety_breakdownの
  // is_designated引数と同じ、交通ストレスと共有の材料タグ）。
  const designationAdjustment = [
    "case",
    ["!=", ["coalesce", ["get", "designation"], ""], ""],
    recipe.designation_adjustment,
    0,
  ];

  const motorVehicleNoOverride = ["==", ["coalesce", ["get", "motor_vehicle_no"], false], true];

  const formula = [
    "max",
    1,
    [
      "min",
      4,
      [
        "+",
        base,
        cyclewayAdjustment,
        maxspeedAdjustment,
        lanesAdjustment,
        litAdjustment,
        tunnelAdjustment,
        designationAdjustment,
      ],
    ],
  ];

  // 適用順序はsafety_breakdownと同じ: (1)highway未登録→UNKNOWN_LEVEL、
  // (2)motor_vehicle=no→1固定（他の補正より優先）、(3)それ以外はbase+各補正をクランプ。
  return ["case", ["!", hasBase], UNKNOWN_LEVEL, motorVehicleNoOverride, 1, formula];
}

// ポップアップ（MapView.tsx）はMapLibreのペイント式ではなくクリック時の単発表示のため、
// レイヤーのpaint/filterとは別に、同じexpressionを@maplibre/maplibre-gl-style-specの評価器で
// 単発評価する。trafficStressExpression.ts: evaluateTrafficStressLevelと同じ理由
// （判定ロジックを3箇所目に増やさない）。戻り値はundefined/-1（判定対象外）ならnull。
export function evaluateSafetyLevel(
  properties: Record<string, unknown>,
  recipe: SafetyRecipe = DEFAULT_SAFETY_RECIPE,
): number | null {
  const parsed = createExpression(buildSafetyExpression(recipe));
  if (parsed.result !== "success") {
    // buildSafetyExpressionは既定・上書き問わずSafetyRecipeの型で閉じており、構文エラーに
    // なりうる自由入力を受け取らないため、到達したらexpression組み立て側のバグ。
    const messages = parsed.value.map((e: { message: string }) => e.message).join(", ");
    throw new Error(`安全度expressionの構築に失敗しました: ${messages}`);
  }
  const level = parsed.value.evaluate({ zoom: 0 }, { type: "Unknown", properties });
  return level === UNKNOWN_LEVEL ? null : (level as number);
}
