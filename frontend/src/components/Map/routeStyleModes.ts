// ルートレイヤー（有向・選択中ルート基準のデータ）の色分けモード定義。
//
// 路面レイヤーの絞り込み軸（roadFilterAxes.ts、無方向・地域固定データのタイル）との対比:
// - ここで扱うのは進行方向で意味が変わる（FROM-TOで逆転する）有向データと、時間で変わる
//   データ。ルートが決まって初めて計算できるため、表示対象は選択中ルートの線上のみ
// - データ源はルート生成時に計算済みのRouteSegmentDetail（segments）。タイル取得は無く、
//   色分けの切り替えはMapLibreのline-color式・フィルタ式の差し替えだけで完結する
// - ルート未選択時はレイヤー自体が使えない（UI側で非活性）
// 将来、トラフィック等「ルート沿いに出す有向・時間変化データ」もここへモードを足す。

import { debugLog } from "@/lib/debugLog";
import type { LegendEntry } from "./legendFilter";
import type { AxisShape, CatalogAxis } from "./axisLayers";
import axisCatalog from "@/types/generated/axis-catalog.json";

// 改善計画T440: 以前は"wind"以外に"gradient"/"road"/"difficulty"も固定文字列unionの
// 一員だったが、gradient/roadはsupports_route_coloring軸から動的に生成されるように
// なったため、固定IDでは表現しきれなくなった。"difficulty"（対応する軸を持たない唯一の
// 例外、下記DIFFICULTY_MODE参照）だけを固定文字列として残す。
export type RouteStyleModeId = "difficulty" | (string & {});

export interface RouteStyleMode {
  id: RouteStyleModeId;
  /** モード選択メニューに出す名前 */
  label: string;
  legend: LegendEntry[];
  /** MapLibreのline-colorに渡すスタイル式 */
  colorExpression: unknown[];
}

const COLOR_EASY = "#16a34a";
const COLOR_HARD = "#dc2626";
export const COLOR_NO_DATA = "#9ca3af";
export const COLOR_DOWNHILL = "#0284c7";
// 改善計画T423: 「評価軸」グループの勾配（gradientAxisLayer.ts）が、ルート確定後の
// gradient色分け（下記）と同じ配色・しきい値を使うためexportする——両者とも
// gradient_percent（符号付き%）という同じ単位・スケールの値を塗るため（風の場合と異なり、
// pre-route/post-routeで値のスケールが変わらない。domain/gradient.pyのモジュールdocstring・
// windAxisLayer.tsのWIND_AXIS_THRESHOLDSコメント参照——風はpre-route[m/s]・post-route
// [正規化済みdifficulty 0-100]で単位自体が異なるため色分けも独立に持つ）。
export const GRADIENT_COLOR_HARD = COLOR_HARD;
// 改善計画T440: 軸スタジオのdisplay_thresholds_overrideが未設定のときのデフォルト値
// （既定の段階境界）。値そのものはこれ以上フロント側の色分けロジックの前提にならない
// ——buildRangeSteppedModeは要素数に関わらず動作する。
export const GRADIENT_BOUNDARIES: readonly number[] = [-2, 2, 6, 10];
// 改善計画T352の3段階固定色（easy/normal/hard）は、改善計画T440でinterpolateColors
// （下記）による段階数に応じた自動生成へ置き換わったため撤去した。

// 数値プロパティの段階分け（凡例カテゴリ）から色式とフィルタ述語付き凡例を組み立てる。
// boundaries[i]は「カテゴリiとi+1の境界値」（カテゴリ数-1個）。値がnull（データ欠落）の
// カテゴリは別枠で扱う。GeoJSONのproperties値はnullが明示的に入るため、to-numberが
// null→0に変換してしまう前に必ずnull判定を先に行う。
//
// valueExpressionはMapLibreの値取得式（`["get", "difficulty"]`のような直下プロパティ、
// または`["get", "wind", ["get", "axis_difficulties"]]`のようなネストしたプロパティへの
// アクセスも渡せる）。改善計画T309: RouteSegmentDetailの軸別難易度が既存7軸固定フィールド
// からaxis_id→difficultyの汎用dict（axis_difficulties）へ置き換わったため、この関数自体は
// 特定のプロパティ名に依存しない形にしてある。
function buildSteppedMode(
  valueExpression: unknown[],
  steps: { key: string; label: string; color: string }[],
  boundaries: readonly number[]
): Pick<RouteStyleMode, "legend" | "colorExpression"> {
  const value: unknown[] = ["to-number", valueExpression];
  const noData: unknown[] = ["==", valueExpression, null];
  const hasData: unknown[] = ["!=", valueExpression, null];

  const colorExpression: unknown[] = ["step", value, steps[0].color];
  boundaries.forEach((boundary, i) => colorExpression.push(boundary, steps[i + 1].color));

  const legend: LegendEntry[] = steps.map(({ key, label, color }, i) => {
    const conditions: unknown[] = [hasData];
    if (i > 0) conditions.push([">=", value, boundaries[i - 1]]);
    if (i < boundaries.length) conditions.push(["<", value, boundaries[i]]);
    return { key, label, color, filter: ["all", ...conditions] };
  });
  legend.push({ key: "nodata", label: "データなし", color: COLOR_NO_DATA, filter: noData });

  return {
    legend,
    colorExpression: ["case", noData, COLOR_NO_DATA, colorExpression],
  };
}

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHsl([r8, g8, b8]: readonly [number, number, number]): [number, number, number] {
  const r = r8 / 255;
  const g = g8 / 255;
  const b = b8 / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return [h * 60, s, l];
}

function hue2rgb(p: number, q: number, tIn: number): number {
  let t = tIn;
  if (t < 0) t += 1;
  if (t > 1) t -= 1;
  if (t < 1 / 6) return p + (q - p) * 6 * t;
  if (t < 1 / 2) return q;
  if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
  return p;
}

function hslToRgb(hDeg: number, s: number, l: number): [number, number, number] {
  const h = (((hDeg % 360) + 360) % 360) / 360;
  if (s === 0) {
    const v = Math.round(l * 255);
    return [v, v, v];
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  return [
    Math.round(hue2rgb(p, q, h + 1 / 3) * 255),
    Math.round(hue2rgb(p, q, h) * 255),
    Math.round(hue2rgb(p, q, h - 1 / 3) * 255),
  ];
}

function rgbToHex([r, g, b]: readonly [number, number, number]): string {
  return (
    "#" +
    [r, g, b]
      .map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0"))
      .join("")
  );
}

// 改善計画T440: 「固定N段階の色配列」をやめ、2色（colorLow/colorHigh）の間をHSL色空間で
// 均等補間したcount色を生成する。境界値の個数（＝段階数）は軸スタジオのdisplay_
// thresholds_overrideが決めるため、この関数は任意のcountに対応する必要がある——固定の
// 色配列（easy/normal/hard等）を持たないことで、軸スタジオでしきい値の個数を変えても
// 色が自動的に追従する。RGB直接補間だと中間色が濁った色になりやすいため
// （例: 緑↔赤の中間が茶色がかる）、色相を短い経路で回るHSL補間にしている
// （green→red: 緑→黄緑→黄→橙→赤という視覚的に自然な遷移になる）。
export function interpolateColors(colorLow: string, colorHigh: string, count: number): string[] {
  if (count <= 1) return [colorLow];
  const [h1, s1, l1] = rgbToHsl(hexToRgb(colorLow));
  const [h2, s2, l2] = rgbToHsl(hexToRgb(colorHigh));
  let dh = h2 - h1;
  if (dh > 180) dh -= 360;
  if (dh < -180) dh += 360;
  return Array.from({ length: count }, (_, i) => {
    const t = i / (count - 1);
    return rgbToHex(hslToRgb(h1 + dh * t, s1 + (s2 - s1) * t, l1 + (l2 - l1) * t));
  });
}

function rangeLabel(boundaries: readonly number[], stepIndex: number, unit: string): string {
  if (boundaries.length === 0) return "";
  if (stepIndex === 0) return `${boundaries[0]}${unit}未満`;
  if (stepIndex === boundaries.length) return `${boundaries[boundaries.length - 1]}${unit}超`;
  return `${boundaries[stepIndex - 1]}〜${boundaries[stepIndex]}${unit}`;
}

// 改善計画T440: 「固定N段階」という前提そのものをやめ、境界値配列（軸スタジオの
// display_thresholds_override、正となるデータ）の長さがそのまま段階数を決める、
// wind・surface_q・gradientを問わず共通の組み立て関数。ラベルは境界値の実際の数字から
// 機械的に生成する（「易しい/普通/難しい」「下り/上り」のような固定語彙は使わない）ため、
// 軸スタジオでしきい値を変えてもラベルが必ず一致する。
function buildRangeSteppedMode(options: {
  id: string;
  label: string;
  valueExpression: unknown[];
  boundaries: readonly number[];
  colorLow: string;
  colorHigh: string;
  unit: string;
}): RouteStyleMode {
  const { id, label, valueExpression, boundaries, colorLow, colorHigh, unit } = options;
  const colors = interpolateColors(colorLow, colorHigh, boundaries.length + 1);
  const steps = colors.map((color, i) => ({
    key: `step-${i}`,
    label: rangeLabel(boundaries, i, unit),
    color,
  }));
  return {
    id,
    label,
    ...buildSteppedMode(valueExpression, steps, boundaries),
  };
}

const DEFAULT_DIFFICULTY_BOUNDARIES: readonly number[] = [33, 66];

// 改善計画T440: 「gradientだけaxis_idで特別扱いする」というハードコード分岐をやめ、
// 軸データ（shape）の属性から符号付き値を直接読むべきかを判定する。
// shape.kind==="breakpoint_linear" && shape.preprocess==="abs"は、軸スタジオで軸を
// 定義する時点で既に選ばれている設定（gradientの実データで確認済み: kind=
// "breakpoint_linear"、preprocess="abs"、terms=[{material:"gradient_percent"}]）。
// termsが単数でない場合は「単一の生材料をそのまま塗る」という単純な対応が成立しないため、
// 通常の（axis_difficulties経由の）abs差難易度経路へフォールバックする。
function isSignedAbsShape(
  shape: AxisShape | undefined
): shape is Extract<AxisShape, { kind: "breakpoint_linear" }> {
  return shape !== undefined && shape.kind === "breakpoint_linear" && shape.preprocess === "abs" && shape.terms.length === 1;
}

// 改善計画T352/T440: supports_route_coloring軸（axis-catalog由来）から、ルート結果の
// 色分けモードを動的に組み立てる。符号付き経路（isSignedAbsShape）とそれ以外（abs差難易度、
// wind・surface_q等）の2経路へ、axis.axis_idの文字列比較ではなくaxis.shapeの属性で
// 分岐する——条件を満たす軸がgradient以外に増えても、コード変更無しでそのまま対応する。
export function routeColorableModeFromAxis(axis: CatalogAxis): RouteStyleMode {
  const boundaries = axis.display_thresholds_override ?? undefined;
  if (isSignedAbsShape(axis.shape)) {
    return buildRangeSteppedMode({
      id: axis.axis_id,
      label: axis.label,
      valueExpression: ["get", axis.shape.terms[0].material],
      boundaries: boundaries ?? GRADIENT_BOUNDARIES,
      colorLow: COLOR_DOWNHILL,
      colorHigh: GRADIENT_COLOR_HARD,
      unit: "%",
    });
  }
  return buildRangeSteppedMode({
    id: axis.axis_id,
    label: `${axis.label}の影響`,
    valueExpression: ["get", axis.axis_id, ["get", "axis_difficulties"]],
    boundaries: boundaries ?? DEFAULT_DIFFICULTY_BOUNDARIES,
    colorLow: COLOR_EASY,
    colorHigh: COLOR_HARD,
    unit: "",
  });
}

// 総合難易度は単一軸ではなく全軸の重み付き合成コストを表示するモードで、特定のaxis_idに
// 紐づかない（評価エンジンが出す合成スコアそのものであり、軸スタジオと同期する対象には
// ならない——ユーザー確認済み: 「総合難易度は、評価した結果の数値そのものになるべき」）。
// gradient/road（旧STATIC_MODES）はT440でdynamicModes側（routeColorableModeFromAxis）へ
// 統合されたため、フロントに直書きされたまま残る唯一のモードになった。
const DIFFICULTY_MODE: RouteStyleMode = {
  id: "difficulty",
  label: "総合難易度",
  // difficultyは標高・風・路面をroute_preference.yaml（またはリクエストの重み上書き）の
  // 重みで合成した0-100の絶対基準難易度（backend/app/domain/difficulty.py）。
  // 「評価モデルが各区間をどれだけ走りにくいと見ているか」をそのまま地図で確認する用途
  // （研究インターフェース改善 §10-5）。
  ...buildSteppedMode(
    ["get", "difficulty"],
    interpolateColors(COLOR_EASY, COLOR_HARD, DEFAULT_DIFFICULTY_BOUNDARIES.length + 1).map((color, i) => ({
      key: `step-${i}`,
      label: rangeLabel(DEFAULT_DIFFICULTY_BOUNDARIES, i, ""),
      color,
    })),
    DEFAULT_DIFFICULTY_BOUNDARIES
  ),
};

// 改善計画T352: supports_route_coloring軸（axis-catalog由来、動的）＋difficulty（総合
// 難易度、固定）を組み合わせた、実際に選択肢として使うモード一覧を組み立てる。
// useAxisCatalog（hooks/useAxisCatalog.ts）が、実行時API取得結果・ビルド時静的
// フォールバックの両方からこの関数で同じ形の一覧を作る（axisLayers.ts:
// rampAxesFromCatalogAxes等と同じ片側importパターン）。
export function routeStyleModesFromCatalogAxes(axes: readonly CatalogAxis[]): RouteStyleMode[] {
  const dynamicModes = axes.filter((axis) => axis.supports_route_coloring).map(routeColorableModeFromAxis);
  return [...dynamicModes, DIFFICULTY_MODE];
}

// ビルド時静的json由来のフォールバック専用値（axisLayers.tsのRAMP_AXES/AXIS_LABELSと
// 同じ位置付け）。useAxisCatalogがGET /api/axis-catalog取得完了までの間・失敗時に使う。
export const ROUTE_STYLE_MODES: readonly RouteStyleMode[] = routeStyleModesFromCatalogAxes(
  axisCatalog.axes as CatalogAxis[]
);

// 改善計画T433: 以前は"wind"を固定文字列でハードコードしており、axis-catalog由来の
// dynamicModesが偶然modes[0]と一致することに暗黙に依存していた（バックエンド側でwindの
// supports_route_coloringをfalseにする、または軸自体をunpublishすると、この定数だけが
// 古い値のまま残り、getRouteStyleModeの「見つからなければmodes[0]」フォールバックで
// 実際の初期選択と定数の値が静かに食い違う——ゼロベースレビュー2026-08-30 §4で指摘）。
// ROUTE_STYLE_MODES[0]から導出することで、この一致をコード上で強制する
// （DIFFICULTY_MODEが常に末尾に含まれるためROUTE_STYLE_MODESが空になることはなく、
// [0]は必ず存在する）。dynamicModesが1件も無くなれば総合難易度へ自動的にフォールバックする。
export const DEFAULT_ROUTE_STYLE_MODE_ID: RouteStyleModeId = ROUTE_STYLE_MODES[0].id;

export function isRouteStyleModeId(
  modes: readonly RouteStyleMode[],
  value: string | null | undefined
): value is RouteStyleModeId {
  return modes.some((mode) => mode.id === value);
}

export function getRouteStyleMode(modes: readonly RouteStyleMode[], id: RouteStyleModeId): RouteStyleMode {
  const found = modes.find((mode) => mode.id === id);
  if (found) return found;
  // 改善計画T466: 指定idが見つからない場合modes[0]へ無警告フォールバックしていた
  // （軸のunpublish等でidが指すモード自体が消えた場合に、選択中の色分けモードが
  // 静かに別のものへ切り替わる。ゼロベース網羅レビュー指摘）。実害を防ぐフォールバック
  // 自体は妥当な設計のため維持しつつ、原因調査ができるよう警告ログだけ追加する。
  debugLog(
    "map:route-style-mode",
    `route style mode "${id}" not found, falling back to "${modes[0]?.id ?? "(no modes)"}"`,
    { requestedId: id, availableIds: modes.map((mode) => mode.id) },
    "warn"
  );
  return modes[0];
}
