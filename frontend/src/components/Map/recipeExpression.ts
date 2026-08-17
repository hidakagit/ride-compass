// 交通ストレス・安全度（trafficStressExpression.ts/safetyExpression.ts）が共有する
// MapLibre expression断片の組み立てヘルパー（改善計画T123）。
// backend/app/domain/recipe.pyの5プリミティブ（clamp_level/threshold_adjustment/
// cycleway_adjustment/flag_adjustment/tag_value_is相当）のTS側ミラー。判定ロジックの
// 正準はPython側で、ここはMapLibre expression（宣言的な式木）として同じ判定を再現するための
// 断片生成にとどめる。両軸の既定値・生成フィクスチャとの整合はtrafficStressExpression.test.ts/
// safetyExpression.test.tsが検証する（T121・T122で確認したPython⇔JS実ドリフト検知の体制は
// このヘルパー化でも変えない）。
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
// 既存のTRAFFIC_STRESS_COLOR_EXPRESSION/SAFETY_COLOR_EXPRESSIONが`coalesce(*, -1)`で
// 使っていたのと同じ値・同じ意味に揃える（MapLibreのcase/match式で数値と`null`を混在させる
// 出力型の扱いが不安定なため、不明は-1という流儀にしてある）。
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
// 「その方向の補正を持たない」ことを表す（安全度のlanesはhigh方向のみ採用）。
// low<highが常に成り立つ前提（*Override APIモデルのvalidate_threshold_orderで検証済み）
// のため、low/highどちらを先に判定しても結果は同じ（両条件は排他的）。
// "has"で先にプロパティの有無を確認してから比較する（caseは短絡評価のため、プロパティが
// 無い場合に["<=", ["get",...], N]がnullと数値を比較してエラーになるのを防ぐ）。
export function thresholdAdjustmentExpr(
  property: string,
  lowThreshold: number | null,
  lowAdjustment: number,
  highThreshold: number | null,
  highAdjustment: number,
): unknown[] {
  const branches: unknown[] = ["case"];
  if (lowThreshold != null) {
    branches.push(["all", ["has", property], ["<=", ["get", property], lowThreshold]], lowAdjustment);
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
// 問わず「該当するかどうか」だけが補正条件（domain/*.py: *_breakdownのis_designated引数と
// 同じ、交通ストレス・安全度で共有の材料タグ）。
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
// 意味論「不明はnull」に合わせる）。`axisLabel`はエラーメッセージ用（例:「交通ストレス」）。
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
