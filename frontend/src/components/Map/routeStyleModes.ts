// ルートレイヤー（有向・選択中ルート基準のデータ）の色分けモード定義。
//
// 路面レイヤーの絞り込み軸（roadFilterAxes.ts、無方向・地域固定データのタイル）との対比:
// - ここで扱うのは進行方向で意味が変わる（FROM-TOで逆転する）有向データと、時間で変わる
//   データ。ルートが決まって初めて計算できるため、表示対象は選択中ルートの線上のみ
// - データ源はルート生成時に計算済みのRouteSegmentDetail（segments）。タイル取得は無く、
//   色分けの切り替えはMapLibreのline-color式・フィルタ式の差し替えだけで完結する
// - ルート未選択時はレイヤー自体が使えない（UI側で非活性）
// 将来、トラフィック等「ルート沿いに出す有向・時間変化データ」もここへモードを足す。

import type { LegendEntry } from "./legendFilter";

export type RouteStyleModeId = "wind" | "gradient";

export interface RouteStyleMode {
  id: RouteStyleModeId;
  /** モード選択メニューに出す名前 */
  label: string;
  legend: LegendEntry[];
  /** MapLibreのline-colorに渡すスタイル式 */
  colorExpression: unknown[];
}

const COLOR_EASY = "#16a34a";
const COLOR_NORMAL = "#f59e0b";
const COLOR_HARD = "#dc2626";
const COLOR_NO_DATA = "#9ca3af";
const COLOR_DOWNHILL = "#0284c7";
const COLOR_UP_MILD = "#eab308";
const COLOR_UP_STEEP = "#ea580c";

// 数値プロパティの段階分け（凡例カテゴリ）から色式とフィルタ述語付き凡例を組み立てる。
// boundaries[i]は「カテゴリiとi+1の境界値」（カテゴリ数-1個）。値がnull（データ欠落）の
// カテゴリは別枠で扱う。GeoJSONのproperties値はnullが明示的に入るため、to-numberが
// null→0に変換してしまう前に必ずnull判定を先に行う。
function buildSteppedMode(
  field: string,
  steps: { key: string; label: string; color: string }[],
  boundaries: number[]
): Pick<RouteStyleMode, "legend" | "colorExpression"> {
  const value: unknown[] = ["to-number", ["get", field]];
  const noData: unknown[] = ["==", ["get", field], null];
  const hasData: unknown[] = ["!=", ["get", field], null];

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

export const ROUTE_STYLE_MODES: RouteStyleMode[] = [
  {
    id: "wind",
    label: "風の影響",
    // wind_difficultyは0-100の難易度。以前は連続補間（0緑〜50アンバー〜100赤）だったが、
    // 凡例タップのカテゴリフィルタと対応させるため3段階のステップへ変更した（見た目は近い）。
    ...buildSteppedMode(
      "wind_difficulty",
      [
        { key: "easy", label: "易しい", color: COLOR_EASY },
        { key: "normal", label: "普通", color: COLOR_NORMAL },
        { key: "hard", label: "難しい", color: COLOR_HARD },
      ],
      [33, 66]
    ),
  },
  {
    id: "gradient",
    label: "勾配",
    // gradient_percentは進行方向基準の符号付き（登り=正）。ルートには進行方向があるため
    // 登り/下りを色で区別できる（無方向の地域レイヤーでは絶対値しか意味を持てない）。
    ...buildSteppedMode(
      "gradient_percent",
      [
        { key: "downhill", label: "下り", color: COLOR_DOWNHILL },
        { key: "flat", label: "平坦", color: COLOR_EASY },
        { key: "up-mild", label: "上り〜6%", color: COLOR_UP_MILD },
        { key: "up-steep", label: "〜10%", color: COLOR_UP_STEEP },
        { key: "up-extreme", label: "10%〜", color: COLOR_HARD },
      ],
      [-2, 2, 6, 10]
    ),
  },
];

export const DEFAULT_ROUTE_STYLE_MODE_ID: RouteStyleModeId = "wind";

export function isRouteStyleModeId(value: string | null | undefined): value is RouteStyleModeId {
  return ROUTE_STYLE_MODES.some((mode) => mode.id === value);
}

export function getRouteStyleMode(id: RouteStyleModeId): RouteStyleMode {
  return ROUTE_STYLE_MODES.find((mode) => mode.id === id) ?? ROUTE_STYLE_MODES[0];
}
