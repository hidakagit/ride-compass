// 二次軸の汎用rampレイヤー定義（改善計画T145b「事実はタイルに、解釈はクライアントに」）。
//
// backendのレジストリ（app/domain/registry_defaults.py）が書き出す生成物
// axis-catalog.json（export_openapi.py）を単一ソースとして、display.kind==="ramp"の軸から
// 地図レイヤー・凡例・パネル項目を自動生成する。新しい軸は、
//   1. backendのレジストリへAxisSpec（display: kind="ramp"）を登録
//   2. タイルへ事実プロパティを焼き込む（way_attribute_counts等）
// だけでフロントのコード変更なしに地図レイヤーとして現れる。
//
// rampの値は tile_inputs から組み立てる。数値材料はΣ property×weight（例: 停止密度 =
// stop_per_km + 0.3×intersection_per_km、backend側の軸内係数
// [domain/difficulty.py: UNSIGNALED_INTERSECTION_WEIGHT等]がカタログ経由で反映される
// ——設計原則2: 片側import。フロントに同じ係数を手書きしない）。プロパティ欠損は
// タイル側が「0をNULLIFでキー省略」した結果なのでcoalesceで0へ倒す
// （_ROAD_SURFACE_TILE_MVT_SQLのコメント参照）。
// 真偽値材料（改善計画T278、例: 舗装質=surface_good、夜間=no_lit/has_tunnel）はMVTの
// 真偽値プロパティを["==",["get",property],true]のような比較でしか読めず数値の重み付け
// 結合が成立しないため、tile_inputs.boolean=trueのときはtrueValue/falseValueで
// 寄与値を直接指定する（weightは無視。domain/axis_display.py: derive_ramp_inputs参照）。

import type { LegendEntry } from "./legendFilter";
import axisCatalog from "@/types/generated/axis-catalog.json";

export interface AxisTileInput {
  property: string;
  weight: number;
  /** true=真偽値材料（改善計画T278）。weightは無視し、trueValue/falseValueで寄与値を直接指定する。 */
  boolean?: boolean;
  /** 材料がタイルプロパティの否定（例: no_lit⟵lit）の場合true。 */
  invert?: boolean;
  trueValue?: number;
  falseValue?: number;
  /** true=タイルプロパティの欠損が「true/falseどちらでもない不明」を表す（例:
   * surface_good、未分類の路面）。欠損時はtrueValue/falseValueどちらにも倒さず、
   * 灰色「不明」表示にする（レビュー指摘の修正、registry.py: TileInputSpec.
   * has_unknown_fallback参照）。既定false（欠損=falseとみなしてよい材料、例:
   * no_lit⟵lit・has_tunnel⟵tunnel）はtrueValue/falseValueへ通常どおり倒す。 */
  hasUnknownFallback?: boolean;
  /** N値文字列材料（改善計画T292、例: highway/bicycle_infra）。タイルプロパティの
   * 文字列値をこの辞書で引いた点数×weightを寄与値とする。未登録値は0扱い
   * （registry.py: TileInputSpec.categories参照）。 */
  categories?: Record<string, number>;
  /** 自己変換材料（改善計画T292、例: maxspeed_kmh/lanes_count）。材料自身が持つ
   * 区分線形breakpointsでタイルプロパティの生値をinterpolateした値×weightを
   * 寄与値とする（registry.py: TileInputSpec.breakpoints参照）。 */
  breakpoints?: readonly (readonly [number, number])[];
}

export interface RampAxis {
  axisId: string;
  label: string;
  category: string;
  tileInputs: readonly AxisTileInput[];
  /** 昇順の色段階境界値。値 < thresholds[0] が最も低い段階 */
  thresholds: readonly number[];
  unit: string;
  note: string;
}

interface CatalogTileInput {
  property: string;
  weight: number;
  boolean?: boolean;
  invert?: boolean;
  true_value?: number;
  false_value?: number;
  has_unknown_fallback?: boolean;
  // JSON生成物（axis-catalog.json）はpydantic model_dump()の未設定optionalフィールドを
  // undefinedではなくnullとしてシリアライズするため、nullも許容する。
  categories?: Record<string, number> | null;
  breakpoints?: (readonly [number, number])[] | null;
}

interface CatalogAxis {
  axis_id: string;
  display: {
    kind: string;
    label: string;
    category: string;
    tile_inputs: CatalogTileInput[];
    thresholds: number[];
    unit: string;
    note: string;
  } | null;
}

// 全軸（ramp/bespoke/noneを問わない）のラベル辞書。区間インスペクタ（改善計画T146）が
// 「一次属性→二次軸スコア」を表示する際、軸ごとに専用UIを持たずカタログのラベルへ
// 汎用的に頼るために使う。windはレジストリ未登録（RoutePreferenceの独立項目、
// domain/registry_defaults.py参照）のためカタログに無く、ここでのみ補う。
export const AXIS_LABELS: Record<string, string> = {
  wind: "風",
  ...Object.fromEntries((axisCatalog.axes as CatalogAxis[]).map((axis) => [axis.axis_id, axis.display?.label ?? axis.axis_id])),
};

export const RAMP_AXES: readonly RampAxis[] = (axisCatalog.axes as CatalogAxis[])
  .filter((axis) => axis.display?.kind === "ramp")
  .map((axis) => ({
    axisId: axis.axis_id,
    label: axis.display!.label,
    category: axis.display!.category,
    tileInputs: axis.display!.tile_inputs.map((input) => ({
      property: input.property,
      weight: input.weight,
      boolean: input.boolean,
      invert: input.invert,
      trueValue: input.true_value,
      falseValue: input.false_value,
      hasUnknownFallback: input.has_unknown_fallback,
      categories: input.categories ?? undefined,
      breakpoints: input.breakpoints ?? undefined,
    })),
    thresholds: axis.display!.thresholds,
    unit: axis.display!.unit,
    note: axis.display!.note,
  }));

/** mapLayers.ts のレイヤーID（チップ・パネル・visibility状態のキー） */
export type AxisMapLayerId = `axis:${string}`;

export function axisMapLayerId(axisId: string): AxisMapLayerId {
  return `axis:${axisId}`;
}

/** MapLibreのlayer id（MapView内部） */
export function axisLineLayerId(axisId: string): string {
  return `region-axis-${axisId}-line`;
}

// 共有ランプ配色（低→高、緑→黄→橙→赤）のアンカー。全ramp軸が同じ配色系統を使うことで
// 「低=緑〜高=赤」という読み方を1回覚えれば全軸に通用させる（軸ごとに独自配色を作らない）。
// 改善計画T292: 段階数（バンド数）は軸によって異なりうる（例: car_stressは複数材料の
// 組み合わせのためthresholdsが4個ちょうどに収まるとは限らない）。以前は4色固定配列
// だったため5段階以上の軸があると末尾の段階が同色に潰れる問題があった
// （旧CAR_STRESS_COLORSが専用の5段階配色を手書きしていた理由そのもの）。
// rampColorForBandはこの4色をアンカーとしてbandCount段階ぶんの色を線形補間で生成する
// ため、bandCount=4のときは既存の4色と完全に一致し（axisLayers.test.ts参照）、
// bandCount≠4の軸でも同じ緑→赤の配色系統のまま段階数ぶんの色を自動生成できる。
const RAMP_COLOR_ANCHORS: readonly [number, string][] = [
  [0, "#4caf50"],
  [1 / 3, "#ffb300"],
  [2 / 3, "#fb8c00"],
  [1, "#e53935"],
];

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHex(rgb: readonly [number, number, number]): string {
  return "#" + rgb.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
}

function lerpColor(a: string, b: string, t: number): string {
  const [ar, ag, ab] = hexToRgb(a);
  const [br, bg, bb] = hexToRgb(b);
  return rgbToHex([ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t]);
}

/** bandCount段階中index番目(0始まり)の色。RAMP_COLOR_ANCHORSを緑(0)→赤(1)の相対位置で
 * 線形補間する。bandCount=4のとき旧AXIS_RAMP_COLORSと完全一致する（axisLayers.test.ts）。 */
export function rampColorForBand(index: number, bandCount: number): string {
  const t = bandCount <= 1 ? 0 : Math.min(1, Math.max(0, index / (bandCount - 1)));
  for (let i = 0; i < RAMP_COLOR_ANCHORS.length - 1; i++) {
    const [t0, c0] = RAMP_COLOR_ANCHORS[i];
    const [t1, c1] = RAMP_COLOR_ANCHORS[i + 1];
    if (t <= t1 || i === RAMP_COLOR_ANCHORS.length - 2) {
      const localT = t1 === t0 ? 0 : Math.min(1, Math.max(0, (t - t0) / (t1 - t0)));
      return lerpColor(c0, c1, localT);
    }
  }
  return RAMP_COLOR_ANCHORS[RAMP_COLOR_ANCHORS.length - 1][1];
}

// 既存4段階軸（gradient/surface_q/stop_density/night/accident等）・staticAttributeLayers.ts
// の非ramp用途（BICYCLE_INFRA/DESIGNATION/TUNNEL/ONEWAY等の固定4色引用）向けの後方互換export。
// rampColorForBand(i, 4)と完全に同じ値（後方互換テストで担保）。
export const AXIS_RAMP_COLORS = [
  rampColorForBand(0, 4),
  rampColorForBand(1, 4),
  rampColorForBand(2, 4),
  rampColorForBand(3, 4),
] as const;

// 「不明」（hasUnknownFallback材料のタイル欠損）専用の灰色。staticAttributeLayers.ts:
// COLOR_UNKNOWNと同じ値（既存の路面レイヤー等の「不明」表現と地図全体で統一する）。
// 循環import回避のため値を複製している（staticAttributeLayers.tsがaxisLayers.tsを
// importする向きのため、逆方向のimportはできない）。
export const COLOR_UNKNOWN = "#9ca3af";

/** hasUnknownFallback=trueのtile_inputについて、対象タイルプロパティが欠損しているか
 * を判定するMapLibre expression。該当する入力を持たない軸はnull（＝不明状態を持たない、
 * 従来どおりstep色分けのみでよい）。 */
export function buildAxisRampUnknownExpression(axis: RampAxis): unknown[] | null {
  const checks = axis.tileInputs
    .filter((input) => input.hasUnknownFallback)
    .map((input) => ["!", ["has", input.property]]);
  if (checks.length === 0) return null;
  return checks.length === 1 ? checks[0] : ["any", ...checks];
}

/** 数値材料はΣ property×weight、真偽値材料（改善計画T278）は
 * ["case", 真偽比較, trueValue, falseValue]、N値文字列材料・自己変換材料（改善計画T292）は
 * それぞれ["match", ...]・["interpolate", ...]で寄与値を組み立てるMapLibre expression。 */
export function buildAxisRampValueExpression(axis: RampAxis): unknown[] {
  const terms = axis.tileInputs.map((input) => {
    if (input.boolean) {
      const comparison = input.invert
        ? ["!=", ["get", input.property], true]
        : ["==", ["get", input.property], true];
      return ["case", comparison, input.trueValue ?? 0, input.falseValue ?? 0];
    }
    if (input.categories) {
      const value = [
        "match",
        ["coalesce", ["get", input.property], "__unknown__"],
        ...Object.entries(input.categories).flatMap(([key, score]) => [key, score * input.weight]),
        0,
      ];
      return value;
    }
    if (input.breakpoints) {
      const value = [
        "interpolate",
        ["linear"],
        ["coalesce", ["get", input.property], input.breakpoints[0][0]],
        ...input.breakpoints.flat(),
      ];
      return input.weight === 1 ? value : ["*", value, input.weight];
    }
    return ["*", ["coalesce", ["get", input.property], 0], input.weight];
  });
  if (terms.length === 1) return terms[0];
  return ["+", ...terms];
}

/** thresholdsによるstep色分けのMapLibre expression。hasUnknownFallbackなtile_inputの
 * プロパティが欠損している場合は、step色分けより先にCOLOR_UNKNOWN（灰色）で塗る
 * （レビュー指摘の修正: 以前はfalseValueへ自動的に倒れ「不明」が「悪い」側の色で
 * 誤表示されていた）。 */
export function buildAxisRampColorExpression(axis: RampAxis): unknown[] {
  const bandCount = axis.thresholds.length + 1;
  const stepExpression: unknown[] = ["step", buildAxisRampValueExpression(axis), rampColorForBand(0, bandCount)];
  axis.thresholds.forEach((threshold, index) => {
    stepExpression.push(threshold, rampColorForBand(index + 1, bandCount));
  });
  const unknownExpression = buildAxisRampUnknownExpression(axis);
  if (unknownExpression === null) return stepExpression;
  return ["case", unknownExpression, COLOR_UNKNOWN, stepExpression];
}

/** 段階の下限（inclusive）・上限（exclusive）。両端はnull（下限/上限なし）。
 * buildAxisRampLegendとMapLayersPanel等の凡例UI・setStaticOverlayFiltersの絞り込みが
 * 同じ境界定義を共有する（片側importで揃える、設計原則2）。 */
function axisRampBand(thresholds: readonly number[], index: number): { lower: number | null; upper: number | null } {
  return {
    lower: index === 0 ? null : thresholds[index - 1],
    upper: index === thresholds.length ? null : thresholds[index],
  };
}

/** 段階ラベル（例: 「1回/km未満」「1〜2回/km」「4回/km以上」）。thresholds.length+1件。 */
function axisRampBandLabel(axis: RampAxis, lower: number | null, upper: number | null): string {
  if (lower === null) return `${upper}${axis.unit}未満`;
  if (upper === null) return `${lower}${axis.unit}以上`;
  return `${lower}〜${upper}${axis.unit}`;
}

/** ramp軸の凡例（改善計画: 地図アイコンチップのグルーピング・研究タブ整理・停止/事故密度の
 * 凡例追加）。既存レイヤー（車ストレス・自転車インフラ等、staticAttributeLayers.ts参照）と
 * 同じLegendEntry型で返すことで、色スウォッチ付きの凡例チェックボックス
 * （MapLayersPanel.tsx: renderLegendCheckboxes）・地図チップの▶展開凡例
 * （MapOverlayControls.tsx: legendDetails）・実際の絞り込み
 * （MapView.tsx: setStaticOverlayFilters、buildCombinedLegendFilterExpression）を
 * 他レイヤーと同じ仕組みでそのまま共有できる（新規UIコンポーネント不要）。
 * filterはbuildAxisRampValueExpression（地図の色分けが使うのと同じ線形結合）への
 * 範囲比較で、実際に塗られる色と凡例が食い違わないようにする。
 * hasUnknownFallbackな軸（例: surface_q）は末尾に「不明」エントリを追加し（既存の
 * staticAttributeLayers.tsの分類レイヤーと同じ「不明・他」の扱い方）、他の段階の
 * filterには「不明ではない」条件を足して二重分類を防ぐ（レビュー指摘の修正）。 */
export function buildAxisRampLegend(axis: RampAxis): LegendEntry[] {
  const valueExpression = buildAxisRampValueExpression(axis);
  const unknownExpression = buildAxisRampUnknownExpression(axis);
  const bandCount = axis.thresholds.length + 1;
  const bands = Array.from({ length: bandCount }, (_, index) => {
    const { lower, upper } = axisRampBand(axis.thresholds, index);
    const filterParts: unknown[] = ["all"];
    if (unknownExpression !== null) filterParts.push(["!", unknownExpression]);
    if (lower !== null) filterParts.push([">=", valueExpression, lower]);
    if (upper !== null) filterParts.push(["<", valueExpression, upper]);
    return {
      key: `${axis.axisId}-${index}`,
      label: axisRampBandLabel(axis, lower, upper),
      color: rampColorForBand(index, bandCount),
      filter: filterParts,
    };
  });
  if (unknownExpression === null) return bands;
  return [
    ...bands,
    {
      key: `${axis.axisId}-unknown`,
      label: "不明",
      color: COLOR_UNKNOWN,
      filter: ["all", unknownExpression],
      isFallback: true,
    },
  ];
}
