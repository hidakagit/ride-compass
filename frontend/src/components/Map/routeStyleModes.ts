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
import type { CatalogAxis } from "./axisLayers";
import axisCatalog from "@/types/generated/axis-catalog.json";

// 改善計画T352: 以前は"wind"も固定文字列unionの一員だったが、supports_route_coloring
// フラグを持つ任意の軸（現状はwindのみ）がaxis-catalogから動的に選択肢へ加わるように
// なったため、固定IDでは表現しきれなくなった。"gradient"/"road"/"difficulty"は
// 引き続き固定（下記STATIC_MODES参照、動的機構では代替できない理由はROUTE_STYLE_MODES
// 定義のコメント参照）、動的な軸IDはstringとして許容する。
export type RouteStyleModeId = "gradient" | "road" | "difficulty" | (string & {});

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
//
// valueExpressionはMapLibreの値取得式（`["get", "difficulty"]`のような直下プロパティ、
// または`["get", "wind", ["get", "axis_difficulties"]]`のようなネストしたプロパティへの
// アクセスも渡せる）。改善計画T309: RouteSegmentDetailの軸別難易度が既存7軸固定フィールド
// からaxis_id→difficultyの汎用dict（axis_difficulties）へ置き換わったため、この関数自体は
// 特定のプロパティ名に依存しない形にしてある。
function buildSteppedMode(
  valueExpression: unknown[],
  steps: { key: string; label: string; color: string }[],
  boundaries: number[]
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

// 改善計画T352: 難易度(0-100)を汎用の3段階（易しい/普通/難しい）で塗る色分けモードを、
// supports_route_coloringを持つ軸（axis-catalog由来、現状はwindのみ）から自動生成する。
// 対象軸はaxis_difficulties[axis_id]（改善計画T309）を値sourceとする——windはこの
// 汎用パターンに素直に乗る単純な難易度軸のため、以前はハードコードしていた"wind"の
// エントリをこの汎用機構へ置き換えた。
export function routeColorableModeFromAxis(axis: CatalogAxis): RouteStyleMode {
  return {
    id: axis.axis_id,
    label: `${axis.label}の影響`,
    ...buildSteppedMode(
      ["get", axis.axis_id, ["get", "axis_difficulties"]],
      [
        { key: "easy", label: "易しい", color: COLOR_EASY },
        { key: "normal", label: "普通", color: COLOR_NORMAL },
        { key: "hard", label: "難しい", color: COLOR_HARD },
      ],
      [33, 66]
    ),
  };
}

// gradient/road/difficultyは汎用機構（supports_route_coloring）の対象外のまま固定で持つ。
// - gradient: 向き（登り/下り）を区別するため、difficulty（前処理でabsを取った絶対値）
//   ではなく符号付きの生材料gradient_percentを直接読む特殊実装（domain/axis_definitions.py:
//   AxisDefinition.supports_route_coloringのdocstring参照）。
// - road: axis_difficulties由来ではなくroad_surface_good（真偽値、区間ごとの舗装判定）を
//   読む別系統のモードで、そもそも軸のdifficultyという概念に乗らない。
// - difficulty: 単一軸ではなく全軸の重み付き合成コスト（総合難易度）を表示するモードで、
//   特定のaxis_idに紐づかない。
const STATIC_MODES: RouteStyleMode[] = [
  {
    id: "gradient",
    label: "勾配",
    // gradient_percentは進行方向基準の符号付き（登り=正）。ルートには進行方向があるため
    // 登り/下りを色で区別できる（無方向の地域レイヤーでは絶対値しか意味を持てない）。
    ...buildSteppedMode(
      ["get", "gradient_percent"],
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
      ["get", "difficulty"],
      [
        { key: "easy", label: "易しい", color: COLOR_EASY },
        { key: "normal", label: "普通", color: COLOR_NORMAL },
        { key: "hard", label: "難しい", color: COLOR_HARD },
      ],
      [33, 66]
    ),
  },
];

// 改善計画T352: supports_route_coloring軸（axis-catalog由来、動的）＋STATIC_MODES
// （gradient/road/difficulty、固定）を組み合わせた、実際に選択肢として使うモード一覧を
// 組み立てる。useAxisCatalog（hooks/useAxisCatalog.ts）が、実行時API取得結果・
// ビルド時静的フォールバックの両方からこの関数で同じ形の一覧を作る（axisLayers.ts:
// rampAxesFromCatalogAxes等と同じ片側importパターン）。
export function routeStyleModesFromCatalogAxes(axes: readonly CatalogAxis[]): RouteStyleMode[] {
  const dynamicModes = axes.filter((axis) => axis.supports_route_coloring).map(routeColorableModeFromAxis);
  return [...dynamicModes, ...STATIC_MODES];
}

// ビルド時静的json由来のフォールバック専用値（axisLayers.tsのRAMP_AXES/AXIS_LABELSと
// 同じ位置付け）。useAxisCatalogがGET /api/axis-catalog取得完了までの間・失敗時に使う。
export const ROUTE_STYLE_MODES: readonly RouteStyleMode[] = routeStyleModesFromCatalogAxes(
  axisCatalog.axes as CatalogAxis[]
);

export const DEFAULT_ROUTE_STYLE_MODE_ID: RouteStyleModeId = "wind";

export function isRouteStyleModeId(
  modes: readonly RouteStyleMode[],
  value: string | null | undefined
): value is RouteStyleModeId {
  return modes.some((mode) => mode.id === value);
}

export function getRouteStyleMode(modes: readonly RouteStyleMode[], id: RouteStyleModeId): RouteStyleMode {
  return modes.find((mode) => mode.id === id) ?? modes[0];
}
