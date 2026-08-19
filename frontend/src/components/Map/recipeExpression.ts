// 車ストレス（carStressExpression.ts、かつては安全度safetyExpression.tsとも共有していたが
// 安全度軸はT148で削除済み）が使うMapLibre expression断片の組み立てヘルパー（改善計画T123）。
// backend/app/domain/recipe.pyの5プリミティブ（clamp_level/threshold_adjustment/
// cycleway_adjustment/flag_adjustment/tag_value_is相当）のTS側ミラー。判定ロジックの
// 正準はPython側で、ここはMapLibre expression（宣言的な式木）として同じ判定を再現するための
// 断片生成にとどめる。既定値・生成フィクスチャとの整合はcarStressExpression.test.tsが検証する
// （T121・T122で確認したPython⇔JS実ドリフト検知の体制はこのヘルパー化でも変えない）。
//
// maplibre-gl本体（paint/filter評価に使う内部実装）は@maplibre/maplibre-gl-style-specを
// ビルド時に自身のdistへ静的に取り込み済みで、node_modulesの本パッケージとは実行時に
// 共有されない（別コピーとしてクライアントバンドルに入る）。バージョンがずれると
// 「地図が塗る色」（maplibre-gl内蔵の評価器）と「ポップアップの表示値」（evaluateRecipeLevel、
// 本パッケージの評価器）が同じexpressionから異なる結果を返しうるため、package.jsonでは
// キャレット無しの固定バージョンにしてある。maplibre-glを更新するときは、
// node_modules/maplibre-gl/package.jsonのdependencies["@maplibre/maplibre-gl-style-spec"]を
// 確認し、このパッケージのバージョンもそれに揃えて更新すること。
import { createExpression } from "@maplibre/maplibre-gl-style-spec";

// 判定対象外（highway未登録、*_breakdownのbase=Noneに対応）を表す出力センチネル。
// 既存のCAR_STRESS_COLOR_EXPRESSIONが`coalesce(*, -1)`で使っていたのと同じ値・同じ意味に
// 揃える（旧SAFETY_COLOR_EXPRESSIONも同じ規約だったが、対応するsafetyExpression.tsごと
// T148で削除済み。MapLibreのcase/match式で数値と`null`を混在させる出力型の扱いが不安定な
// ため、不明は-1という流儀にしてある）。
export const UNKNOWN_LEVEL = -1;

// cycleway系タグの分類（domain/recipe.py: cycleway_adjustment）。cycleway_classは
// _ROAD_SURFACE_TILE_MVT_SQLが'track'|'lane'|'shared'|(キー無し)で焼く。
export function cyclewayAdjustmentExpr(trackAdjustment: number, laneAdjustment: number, sharedAdjustment: number): unknown[] {
  return [
    "match",
    ["coalesce", ["get", "cycleway_class"], ""],
    "track",
    trackAdjustment,
    "lane",
    laneAdjustment,
    "shared",
    sharedAdjustment,
    0,
  ];
}

// 数値材料タグ（maxspeed_kmh/lanes_count）が低い方/高い方の閾値に該当する場合の補正
// （domain/recipe.py: threshold_adjustment）。lowThreshold/highThresholdはnullなら
// 「その方向の補正を持たない」ことを表す（lanesはhigh方向のみ採用）。
// low<highが常に成り立つ前提（*Override APIモデルのvalidate_threshold_orderで検証済み）
// のため、low/highどちらを先に判定しても結果は同じ（両条件は排他的）。
// "has"で先にプロパティの有無を確認してから比較する（caseは短絡評価のため、プロパティが
// 無い場合に["<=", ["get",...], N]がnullと数値を比較してエラーになるのを防ぐ）。
//
// lowSuppressedWhenはlow方向のみを無効化する追加条件（車ストレスのlanes_low、
// 分離自転車道区間では該当しないため。domain/traffic.py: car_stress_breakdownの
// `cycleway_class(tags) == "track"`判定と1:1対応）。high方向・他の呼び出し元
// （maxspeedのlanes）は影響しない。
export function thresholdAdjustmentExpr(
  property: string,
  lowThreshold: number | null,
  lowAdjustment: number,
  highThreshold: number | null,
  highAdjustment: number,
  lowSuppressedWhen?: unknown[],
): unknown[] {
  const branches: unknown[] = ["case"];
  if (lowThreshold != null) {
    const lowCondition = ["all", ["has", property], ["<=", ["get", property], lowThreshold]];
    branches.push(
      lowSuppressedWhen ? ["all", lowCondition, ["!", lowSuppressedWhen]] : lowCondition,
      lowAdjustment,
    );
  }
  if (highThreshold != null) {
    branches.push(["all", ["has", property], [">=", ["get", property], highThreshold]], highAdjustment);
  }
  branches.push(0);
  return branches;
}

// 真偽値の材料タグ（lit/tunnel等）が立っている場合の補正（domain/recipe.py:
// flag_adjustment＋tag_value_is相当）。無ければキー自体が無い＝coalesceでfalse扱い。
export function flagAdjustmentExpr(property: string, adjustment: number): unknown[] {
  return ["case", ["==", ["coalesce", ["get", property], false], true], adjustment, 0];
}

// designationは'emergency_transport'|'critical_logistics'|'both'|(キー無し)。値の種類を
// 問わず「該当するかどうか」だけが補正条件（domain/traffic.py: car_stress_breakdownの
// is_designated引数と同じ材料タグ）。
export function designationAdjustmentExpr(adjustment: number): unknown[] {
  return ["case", ["!=", ["coalesce", ["get", "designation"], ""], ""], adjustment, 0];
}

export function motorVehicleNoOverrideExpr(): unknown[] {
  return ["==", ["coalesce", ["get", "motor_vehicle_no"], false], true];
}

// highwayがbase_by_highwayに登録されているか（登録が無ければ判定対象外、*_breakdownの
// base=Noneに対応）。hasBaseがfalseの場合はbase/formulaが評価されない（呼び出し側のcase式の
// 短絡評価に依存する）ため、matchのfallback値（0）には到達しない。
export function baseByHighwayExpr(baseByHighway: Record<string, number>): { hasBase: unknown[]; base: unknown[] } {
  const baseEntries = Object.entries(baseByHighway).flatMap(([highway, base]) => [highway, base]);
  const highwayKeys = Object.keys(baseByHighway);
  return {
    hasBase: ["in", ["get", "highway"], ["literal", highwayKeys]],
    base: ["match", ["get", "highway"], ...baseEntries, 0],
  };
}

// 「道路適正」（highway別基準値＋cycleway分離度）を1組で返す（domain/recipe.py:
// road_suitability、改善計画: 車との近さ材料の共有元化）。車ストレスが最初に評価する
// 共通部分で、baseByHighwayExpr・cyclewayAdjustmentExprを個別に呼ぶ重複を1箇所へまとめる。
export function roadSuitabilityExpr(
  baseByHighway: Record<string, number>,
  trackAdjustment: number,
  laneAdjustment: number,
  sharedAdjustment: number,
): { hasBase: unknown[]; base: unknown[]; cyclewayAdjustment: unknown[] } {
  const { hasBase, base } = baseByHighwayExpr(baseByHighway);
  const cyclewayAdjustment = cyclewayAdjustmentExpr(trackAdjustment, laneAdjustment, sharedAdjustment);
  return { hasBase, base, cyclewayAdjustment };
}

// carClosenessExpr()の戻り値の形（build*Expression側が呼び出し元から事前計算済みの
// 結果を受け取れるようexportする。MapView.tsx: setStaticOverlayFilters参照）。
export interface CarClosenessExpr {
  hasBase: unknown[];
  base: unknown[];
  cyclewayAdjustment: unknown[];
  maxspeedAdjustment: unknown[];
  lanesHighAdjustment: unknown[];
  designationAdjustment: unknown[];
}

// 「車との近さ」（N2 = 道路適正＋自動車密度）を1組で返す（domain/recipe.py:
// car_closeness、改善計画: 車との近さ材料の共有元化）。車ストレスが共通の土台として
// 評価する材料で、軸固有の補正（車線数[少ない方]）は呼び出し側がこの結果へ追加する。
export function carClosenessExpr(
  roadSuitabilityRecipe: {
    base_by_highway: Record<string, number>;
    cycleway_track_adjustment: number;
    cycleway_lane_adjustment: number;
    cycleway_shared_adjustment: number;
  },
  motorVehicleDensityRecipe: {
    maxspeed_low_threshold: number;
    maxspeed_low_adjustment: number;
    maxspeed_high_threshold: number;
    maxspeed_high_adjustment: number;
    lanes_high_threshold: number;
    lanes_high_adjustment: number;
    designation_adjustment: number;
  },
): CarClosenessExpr {
  const { hasBase, base, cyclewayAdjustment } = roadSuitabilityExpr(
    roadSuitabilityRecipe.base_by_highway,
    roadSuitabilityRecipe.cycleway_track_adjustment,
    roadSuitabilityRecipe.cycleway_lane_adjustment,
    roadSuitabilityRecipe.cycleway_shared_adjustment,
  );
  const maxspeedAdjustment = thresholdAdjustmentExpr(
    "maxspeed_kmh",
    motorVehicleDensityRecipe.maxspeed_low_threshold,
    motorVehicleDensityRecipe.maxspeed_low_adjustment,
    motorVehicleDensityRecipe.maxspeed_high_threshold,
    motorVehicleDensityRecipe.maxspeed_high_adjustment,
  );
  const lanesHighAdjustment = thresholdAdjustmentExpr(
    "lanes_count",
    null,
    0,
    motorVehicleDensityRecipe.lanes_high_threshold,
    motorVehicleDensityRecipe.lanes_high_adjustment,
  );
  const designationAdjustment = designationAdjustmentExpr(motorVehicleDensityRecipe.designation_adjustment);
  return { hasBase, base, cyclewayAdjustment, maxspeedAdjustment, lanesHighAdjustment, designationAdjustment };
}

// base＋各補正の合計をmin〜maxへクランプする（domain/recipe.py: clamp_level）。
export function clampLevelExpr(min: number, max: number, terms: unknown[]): unknown[] {
  return ["max", min, ["min", max, ["+", ...terms]]];
}

// 適用順序はdomain/*.py: *_breakdownと同じ: (1)highway未登録→UNKNOWN_LEVEL、
// (2)motor_vehicle=no→1固定（他の補正より優先）、(3)それ以外はclamp済みformula。
export function buildRecipeLevelExpression(hasBase: unknown[], formula: unknown[]): unknown[] {
  return ["case", ["!", hasBase], UNKNOWN_LEVEL, motorVehicleNoOverrideExpr(), 1, formula];
}

// ポップアップ（MapView.tsx）はMapLibreのペイント式ではなくクリック時の単発表示のため、
// レイヤーのpaint/filterとは別に、同じexpressionを@maplibre/maplibre-gl-style-specの評価器で
// 単発評価する。build*Expressionと実装を分けない（判定ロジックを3箇所目に増やさない）ための
// 共通経路。戻り値はundefined/UNKNOWN_LEVELならnull（RoadSurfacePopupPropertiesの従来の
// 意味論「不明はnull」に合わせる）。`axisLabel`はエラーメッセージ用（例:「車ストレス」）。
export function evaluateRecipeLevel(expression: unknown[], properties: Record<string, unknown>, axisLabel: string): number | null {
  const parsed = createExpression(expression);
  if (parsed.result !== "success") {
    // build*Expressionは既定・上書き問わずRecipeの型で閉じており、構文エラーになりうる
    // 自由入力を受け取らないため、到達したらexpression組み立て側のバグ。
    const messages = parsed.value.map((e: { message: string }) => e.message).join(", ");
    throw new Error(`${axisLabel}expressionの構築に失敗しました: ${messages}`);
  }
  const level = parsed.value.evaluate({ zoom: 0 }, { type: "Unknown", properties });
  return level === UNKNOWN_LEVEL ? null : (level as number);
}
