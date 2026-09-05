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
import type { CatalogAxis } from "./axisLayers";
import axisCatalog from "@/types/generated/axis-catalog.json";
import {
  COLOR_EASY,
  COLOR_HARD,
  COLOR_NO_DATA,
  DEFAULT_DIFFICULTY_BOUNDARIES,
  interpolateColors,
  valueScaleFor,
  type MapValueKind,
} from "./valueScale";

// 改善計画T440: 以前は"wind"以外に"gradient"/"road"/"difficulty"も固定文字列unionの
// 一員だったが、gradient/roadは公開軸から動的に生成されるようになったため、固定IDでは
// 表現しきれなくなった。"difficulty"（対応する軸を持たない唯一の例外、下記
// DIFFICULTY_MODE参照）だけを固定文字列として残す。
export type RouteStyleModeId = "difficulty" | "none" | (string & {});

/** レンズ（地図を何で塗るか）の識別子。`"none"`（塗らない）・`"difficulty"`（総合難易度）
 * 以外は公開軸のaxis_id。ルート前は全道路（rampタイル・専用配信）、ルート後はルート線
 * （`axis_difficulties`）を同じ識別子で塗る。 */
export type LensId = RouteStyleModeId;
export const LENS_NONE_ID: LensId = "none";
export const LENS_DIFFICULTY_ID: LensId = "difficulty";

export interface RouteStyleMode {
  id: RouteStyleModeId;
  /** モード選択メニューに出す名前 */
  label: string;
  legend: LegendEntry[];
  /** MapLibreのline-colorに渡すスタイル式 */
  colorExpression: unknown[];
}

export { COLOR_NO_DATA };

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

// 公開軸（axis-catalog由来）から、ルート結果の色分けモードを動的に組み立てる。地図が塗る値の
// 種類（符号付き材料か難易度か）・単位・既定しきい値はbackendの`map_value_kind`/
// `map_value_unit`（domain/dynamic_way_values.py）とvalueScale.tsが決め、ルート確定前の
// 専用way値レイヤー（dedicatedWayValueLayer.ts）と同じスケール・配色になる。
export function routeColorableModeFromAxis(axis: CatalogAxis): RouteStyleMode {
  const kind: MapValueKind = axis.map_value_kind ?? "difficulty";
  const scale = valueScaleFor(kind);
  const boundaries = axis.display_thresholds_override ?? scale.defaultBoundaries;
  if (kind === "signed_material" && axis.shape?.kind === "breakpoint_linear") {
    return buildRangeSteppedMode({
      id: axis.axis_id,
      label: axis.label,
      valueExpression: ["get", axis.shape.terms[0].material, ["get", "material_values"]],
      boundaries,
      colorLow: scale.colorLow,
      colorHigh: scale.colorHigh,
      unit: axis.map_value_unit ?? "",
    });
  }
  return buildRangeSteppedMode({
    id: axis.axis_id,
    label: `${axis.label}の影響`,
    valueExpression: ["get", axis.axis_id, ["get", "axis_difficulties"]],
    boundaries,
    colorLow: scale.colorLow,
    colorHigh: scale.colorHigh,
    unit: axis.map_value_unit ?? "",
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

// レンズ「なし」: ルート線を単色（候補線の非選択色と同じ中立グレー）で描き、凡例を持たない。
const NONE_MODE: RouteStyleMode = {
  id: LENS_NONE_ID,
  label: "なし",
  legend: [],
  colorExpression: ["to-color", "#64748b"],
};

// 公開軸すべて（axis-catalog由来、動的）＋difficulty（総合難易度、固定）＋NONE_MODEを
// 組み合わせた、レンズ（LensControl）の選択肢一覧を組み立てる。軸ごとの絞り込みは行わない
// （重み0の軸もレンズには選べる、公開軸を無条件で対象にする）。
// useAxisCatalog（hooks/useAxisCatalog.ts）が、実行時API取得結果・ビルド時静的
// フォールバックの両方からこの関数で同じ形の一覧を作る（axisLayers.ts:
// rampAxesFromCatalogAxes等と同じ片側importパターン）。
export function routeStyleModesFromCatalogAxes(axes: readonly CatalogAxis[]): RouteStyleMode[] {
  const dynamicModes = axes.map(routeColorableModeFromAxis);
  return [...dynamicModes, DIFFICULTY_MODE, NONE_MODE];
}

// ビルド時静的json由来のフォールバック専用値（axisLayers.tsのRAMP_AXES/AXIS_LABELSと
// 同じ位置付け）。useAxisCatalogがGET /api/axis-catalog取得完了までの間・失敗時に使う。
export const ROUTE_STYLE_MODES: readonly RouteStyleMode[] = routeStyleModesFromCatalogAxes(
  axisCatalog.axes as CatalogAxis[]
);

// 既定のレンズは総合難易度（軸の公開状態に依存せず常に存在するモード）。
export const DEFAULT_ROUTE_STYLE_MODE_ID: RouteStyleModeId = LENS_DIFFICULTY_ID;

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
