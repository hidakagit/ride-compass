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
// 正準はPython側。ここは同じレシピをMapLibre expressionとして再現するミラー）。
// 既定レシピはtypes/generated/traffic-stress-recipe.json（export_openapi.pyがPython側の
// DEFAULT_TRAFFIC_STRESS_RECIPEから書き出す）から読み、手動同期を避ける
// （trafficStressExpression.test.tsがPython側との整合を検証する）。
//
// 出力は1〜5、または「判定対象外（highway未登録）」を表すセンチネル-1
// （既存のTRAFFIC_STRESS_COLOR_EXPRESSIONが`["coalesce", ["get","traffic_stress"], -1]`で
// 使っていたのと同じ「不明はnullでなく-1」という流儀に合わせる。MapLibreのcase/match式で
// 数値と `null` を混在させる出力型の扱いが不安定なため）。

// maplibre-gl本体（paint/filter評価に使う内部実装）は@maplibre/maplibre-gl-style-specを
// ビルド時に自身のdistへ静的に取り込み済みで、node_modulesの本パッケージとは実行時に
// 共有されない（別コピーとしてクライアントバンドルに入る）。バージョンがずれると
// 「地図が塗る色」（maplibre-gl内蔵の評価器）と「ポップアップの表示値」（このevaluateTrafficStressLevel、
// 本パッケージの評価器）が同じexpressionから異なる結果を返しうるため、package.jsonでは
// キャレット無しの固定バージョンにしてある。maplibre-glを更新するときは、
// node_modules/maplibre-gl/package.jsonのdependencies["@maplibre/maplibre-gl-style-spec"]を
// 確認し、このパッケージのバージョンもそれに揃えて更新すること。
import { createExpression } from "@maplibre/maplibre-gl-style-spec";
import type { TrafficStressRecipeOverride } from "@/types/route";
import defaultRecipeJson from "@/types/generated/traffic-stress-recipe.json";

export type TrafficStressRecipe = TrafficStressRecipeOverride;

export const DEFAULT_TRAFFIC_STRESS_RECIPE: TrafficStressRecipe = defaultRecipeJson;

// 判定対象外（highway未登録、traffic_stress_breakdownのbase=Noneに対応）を表す出力センチネル。
// 既存のTRAFFIC_STRESS_COLOR_EXPRESSIONが`coalesce(traffic_stress, -1)`で使っていたのと
// 同じ値・同じ意味に揃える。
const UNKNOWN_LEVEL = -1;

export function buildTrafficStressExpression(recipe: TrafficStressRecipe): unknown[] {
  const baseEntries = Object.entries(recipe.base_by_highway).flatMap(([highway, base]) => [highway, base]);
  const highwayKeys = Object.keys(recipe.base_by_highway);

  // highwayがbase_by_highwayに登録されているか（登録が無ければ判定対象外、traffic_stress_
  // breakdownのbase=Noneに対応）。この判定でUNKNOWN_LEVELへ分岐させるため、以下のbase/formula
  // はhasBaseがtrueの場合しか評価されない（case式の短絡評価）。matchのfallback値は
  // 到達しないため任意の数値でよい。
  const hasBase = ["in", ["get", "highway"], ["literal", highwayKeys]];
  const base = ["match", ["get", "highway"], ...baseEntries, 0];

  // cycleway_classは_ROAD_SURFACE_TILE_MVT_SQLが'track'|'lane'|'shared'|(キー無し)で焼く。
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

  const lanesAdjustment = [
    "case",
    ["all", ["has", "lanes_count"], [">=", ["get", "lanes_count"], recipe.lanes_high_threshold]],
    recipe.lanes_high_adjustment,
    ["all", ["has", "lanes_count"], ["<=", ["get", "lanes_count"], recipe.lanes_low_threshold]],
    recipe.lanes_low_adjustment,
    0,
  ];

  // designationは'emergency_transport'|'critical_logistics'|'both'|(キー無し)。
  // 値の種類を問わず「該当するかどうか」だけがtraffic_stressへの補正条件
  // （domain/traffic.py: traffic_stress_breakdownのis_designated引数と同じ）。
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
    ["min", 5, ["+", base, cyclewayAdjustment, maxspeedAdjustment, lanesAdjustment, designationAdjustment]],
  ];

  // 適用順序はtraffic_stress_breakdownと同じ: (1)highway未登録→UNKNOWN_LEVEL、
  // (2)motor_vehicle=no→1固定（他の補正より優先）、(3)それ以外はbase+各補正をクランプ。
  return ["case", ["!", hasBase], UNKNOWN_LEVEL, motorVehicleNoOverride, 1, formula];
}

// ポップアップ（MapView.tsx）はMapLibreのペイント式ではなくクリック時の単発表示のため、
// レイヤーのpaint/filterとは別に、同じexpressionを@maplibre/maplibre-gl-style-specの評価器で
// 単発評価する。buildTrafficStressExpressionと実装を分けない（判定ロジックを3箇所目に
// 増やさない）ための共通経路。戻り値はundefined/-1（判定対象外）ならnull
// （RoadSurfacePopupPropertiesの従来の意味論「不明はnull」に合わせる）。
export function evaluateTrafficStressLevel(
  properties: Record<string, unknown>,
  recipe: TrafficStressRecipe = DEFAULT_TRAFFIC_STRESS_RECIPE,
): number | null {
  const parsed = createExpression(buildTrafficStressExpression(recipe));
  if (parsed.result !== "success") {
    // buildTrafficStressExpressionは既定・上書き問わずTrafficStressRecipeの型で閉じており、
    // 構文エラーになりうる自由入力を受け取らないため、到達したらexpression組み立て側のバグ。
    const messages = parsed.value.map((e: { message: string }) => e.message).join(", ");
    throw new Error(`交通ストレスexpressionの構築に失敗しました: ${messages}`);
  }
  const level = parsed.value.evaluate({ zoom: 0 }, { type: "Unknown", properties });
  return level === UNKNOWN_LEVEL ? null : (level as number);
}
