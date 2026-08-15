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

export type RouteStyleModeId = "wind" | "gradient" | "road" | "difficulty";

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
        // 範囲表記は「〜10%」のような下限が読み取れない書き方を避け、境界値を両側とも
        // 明示する（初見ユーザー向けの表記統一、T30）
        { key: "downhill", label: "下り", color: COLOR_DOWNHILL },
        { key: "flat", label: "平坦", color: COLOR_EASY },
        { key: "up-mild", label: "上り 2〜6%", color: COLOR_UP_MILD },
        { key: "up-steep", label: "上り 6〜10%", color: COLOR_UP_STEEP },
        { key: "up-extreme", label: "上り 10%超", color: COLOR_HARD },
      ],
      [-2, 2, 6, 10]
    ),
  },
  {
    id: "road",
    // 地域レイヤー「道路情報」（roadFilterAxes.tsの路面の種類）と同じ「路面」を名乗ると
    // 別物なのに同名になるため、凡例（舗装路/未舗装路）と一致するこの名前にする（T30）
    label: "舗装/未舗装",
    // road_surface_goodは3値（true=舗装/false=未舗装/null=不明）の真偽値プロパティのため、
    // 数値の段階分け（buildSteppedMode）は使わず判定値をそのままcase式・凡例フィルタにする。
    // 地域の路面レイヤー（roadFilterAxes.ts、タイルのsurfaceタグ）とは別系統で、こちらは
    // ルート生成時にエンジンが判定した区間ごとの値（segments[].road_surface_good）を表示する。
    // segmentsに元から入っている値のため、モード追加によるデータ取得・API変更は無い
    // （研究インターフェース改善 §10-5）。
    legend: [
      { key: "paved", label: "舗装路", color: COLOR_EASY, filter: ["==", ["get", "road_surface_good"], true] },
      { key: "unpaved", label: "未舗装路", color: COLOR_HARD, filter: ["==", ["get", "road_surface_good"], false] },
      { key: "nodata", label: "データなし", color: COLOR_NO_DATA, filter: ["==", ["get", "road_surface_good"], null] },
    ],
    colorExpression: [
      "case",
      ["==", ["get", "road_surface_good"], null],
      COLOR_NO_DATA,
      ["==", ["get", "road_surface_good"], true],
      COLOR_EASY,
      COLOR_HARD,
    ],
  },
  {
    id: "difficulty",
    label: "総合難易度",
    // difficultyは標高・風・路面をroute_preference.yaml（またはリクエストの重み上書き）の
    // 重みで合成した0-100の絶対基準難易度（backend/app/domain/difficulty.py）。
    // 「評価モデルが各区間をどれだけ走りにくいと見ているか」をそのまま地図で確認する用途
    // （研究インターフェース改善 §10-5）。
    ...buildSteppedMode(
      "difficulty",
      [
        { key: "easy", label: "易しい", color: COLOR_EASY },
        { key: "normal", label: "普通", color: COLOR_NORMAL },
        { key: "hard", label: "難しい", color: COLOR_HARD },
      ],
      [33, 66]
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
