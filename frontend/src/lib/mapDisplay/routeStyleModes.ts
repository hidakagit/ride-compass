// ルートレイヤー（有向・選択中ルート基準のデータ）の色分けモード定義。
//
// 道路の線の分類（無方向・地域固定データのタイル）との対比:
// - ここで扱うのは進行方向で意味が変わる（FROM-TOで逆転する）有向データと、時間で変わる
//   データ。ルートが決まって初めて計算できるため、表示対象は選択中ルートの線上のみ
// - データ源はルート生成時に計算済みのRouteSegmentDetail（segments）。タイル取得は無く、
//   色分けの切り替えはMapLibreのline-color式・フィルタ式の差し替えだけで完結する
// - ルート未選択時はレイヤー自体が使えない（UI側で非活性）
// 将来、トラフィック等「ルート沿いに出す有向・時間変化データ」もここへモードを足す。

import palette from "@/types/generated/palette.json";
import type { LegendEntry } from "./legendFilter";
import { bandLabelsForBandCount, LEGEND_NO_DATA_KEY, legendBandKey, rangeStepLabel } from "./mapColorLegend";
import type { AxisCatalogEntry } from "@/types/route";
import { bandColorsFor, COLOR_NO_DATA, DEFAULT_DIFFICULTY_BOUNDARIES, type MapValueKind } from "./valueScale";

// gradient/roadは公開軸から動的に生成されるため固定IDでは表現しきれない。
// "difficulty"（対応する軸を持たない唯一の例外、下記DIFFICULTY_MODE参照）だけを
// 固定文字列として残す。
type RouteStyleModeId = "difficulty" | "none" | (string & {});

/** レンズ（地図を何で塗るか）の識別子。`"none"`（塗らない）・`"difficulty"`（総合難易度）
 * 以外は公開軸のaxis_id。ルート前は全道路（rampタイル・専用配信）、ルート後はルート線
 * （`axis_difficulties`）を同じ識別子で塗る。 */
export type LensId = RouteStyleModeId;
/** レンズの中立色。「なし」「総合難易度」のようにどの軸にも紐づかないレンズと、
 * 軸色が未設定の軸のフォールバックで使う（候補線の非選択色と同じ）。 */
export const LENS_NEUTRAL_COLOR = palette.semantic.neutral;

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

// 数値プロパティの段階分け（凡例カテゴリ）から色式とフィルタ述語付き凡例を組み立てる。
// boundaries[i]は「カテゴリiとi+1の境界値」（カテゴリ数-1個）。値がnull（データ欠落）の
// カテゴリは別枠で扱う。GeoJSONのproperties値はnullが明示的に入るため、to-numberが
// null→0に変換してしまう前に必ずnull判定を先に行う。
//
// valueExpressionはMapLibreの値取得式（`["get", "difficulty"]`のような直下プロパティ、
// または`["get", "wind", ["get", "axis_difficulties"]]`のようなネストしたプロパティへの
// アクセスも渡せる）。RouteSegmentDetailの軸別難易度はaxis_id→difficultyの汎用dict
// （axis_difficulties）のため、この関数自体は特定のプロパティ名に依存しない形にしてある。
function buildSteppedMode(
  valueExpression: unknown[],
  steps: { key: string; label: string; color: string }[],
  boundaries: readonly number[],
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
  legend.push({ key: LEGEND_NO_DATA_KEY, label: "データなし", color: COLOR_NO_DATA, filter: noData, isFallback: true });

  return {
    legend,
    colorExpression: ["case", noData, COLOR_NO_DATA, colorExpression],
  };
}

/** 境界値配列の`stepIndex`番目の段階を文字にする。表記規則は
 * `mapColorLegend.ts: rangeStepLabel`が唯一の出どころで、ここは段階indexを上下の境界へ
 * 直すだけ（`axisLayers.ts: axisRampBand`と同じ直し方）。 */
function rangeLabel(boundaries: readonly number[], stepIndex: number, unit: string): string {
  return rangeStepLabel(
    stepIndex === 0 ? null : boundaries[stepIndex - 1],
    stepIndex === boundaries.length ? null : boundaries[stepIndex],
    unit,
  );
}

// 「固定N段階」という前提を持たず、境界値配列（軸カタログのmap_value_thresholds、
// 正となるデータ）の長さがそのまま段階数を決める、wind・surface_q・gradientを問わず
// 共通の組み立て関数。ラベルは境界値の実際の数字から
// 機械的に生成する（「易しい/普通/難しい」「下り/上り」のような固定語彙は使わない）ため、
// 軸スタジオでしきい値を変えてもラベルが必ず一致する。
function buildRangeSteppedMode(options: {
  id: string;
  label: string;
  valueExpression: unknown[];
  kind: MapValueKind;
  boundaries: readonly number[];
  unit: string;
  bandLabels?: readonly string[] | null;
}): RouteStyleMode {
  const { id, label, valueExpression, kind, boundaries, unit, bandLabels } = options;
  const colors = bandColorsFor(kind, boundaries);
  const labels = bandLabelsForBandCount(bandLabels, boundaries.length + 1);
  const steps = colors.map((color, i) => ({
    key: legendBandKey(i),
    label: labels ? `${labels[i]}（${rangeLabel(boundaries, i, unit)}）` : rangeLabel(boundaries, i, unit),
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
function routeColorableModeFromAxis(axis: AxisCatalogEntry): RouteStyleMode {
  const kind: MapValueKind = axis.map_value_kind ?? "difficulty";
  const boundaries = axis.map_value_thresholds ?? DEFAULT_DIFFICULTY_BOUNDARIES;
  // backendは`map_value_kind`が`signed_material`になる条件としてterms 1件を要求するが
  // （domain/dynamic_way_values.py）、その不変条件はカタログのJSONには現れない。
  // 材料が引けないときは難易度モードへ倒す（塗れないより、軸の難易度で塗る方が近い）。
  const signedMaterial = axis.shape?.kind === "breakpoint_linear" ? axis.shape.terms[0]?.material : undefined;
  if (kind === "signed_material" && signedMaterial) {
    return buildRangeSteppedMode({
      id: axis.axis_id,
      label: axis.label,
      valueExpression: ["get", signedMaterial, ["get", "material_values"]],
      kind,
      boundaries,
      unit: axis.map_value_unit ?? "",
      bandLabels: axis.display_band_labels_override,
    });
  }
  return buildRangeSteppedMode({
    id: axis.axis_id,
    label: `${axis.label}の影響`,
    valueExpression: ["get", axis.axis_id, ["get", "axis_difficulties"]],
    kind: "difficulty",
    boundaries,
    unit: axis.map_value_unit ?? "",
    bandLabels: axis.display_band_labels_override,
  });
}

// 総合難易度は単一軸ではなく全軸の重み付き合成コストを表示するモードで、特定のaxis_idに
// 紐づかない（評価エンジンが出す合成スコアそのものであり、軸スタジオと同期する対象には
// ならない）。フロントに直書きされたまま残る唯一のモード。
const DIFFICULTY_MODE: RouteStyleMode = {
  id: "difficulty",
  label: "総合難易度",
  // difficultyは各公開軸を、軸定義の既定重み（またはリクエストの重み上書き）で合成した
  // 0-100の絶対基準難易度（backend/app/domain/difficulty.py）。
  // 「評価モデルが各区間をどれだけ走りにくいと見ているか」をそのまま地図で確認する用途
  // （研究インターフェース改善 §10-5）。
  ...buildSteppedMode(
    ["get", "difficulty"],
    bandColorsFor("difficulty", DEFAULT_DIFFICULTY_BOUNDARIES).map((color, i) => ({
      key: legendBandKey(i),
      label: rangeLabel(DEFAULT_DIFFICULTY_BOUNDARIES, i, ""),
      color,
    })),
    DEFAULT_DIFFICULTY_BOUNDARIES,
  ),
};

// レンズ「なし」: ルート線を単色（候補線の非選択色と同じ中立グレー）で描き、凡例を持たない。
const NONE_MODE: RouteStyleMode = {
  id: LENS_NONE_ID,
  label: "なし",
  legend: [],
  colorExpression: ["to-color", LENS_NEUTRAL_COLOR],
};

/** 軸に紐づかない固定レンズの表示名。`LensControl`のピル・一覧はここから引く
 * （同じ語彙をUI側でも直書きすると、モード名を変えたときに片方だけ古いまま残る）。 */
export const FIXED_LENS_LABELS: Record<string, string> = {
  [LENS_NONE_ID]: NONE_MODE.label,
  [LENS_DIFFICULTY_ID]: DIFFICULTY_MODE.label,
};

// 公開軸すべて（axis-catalog由来、動的）＋difficulty（総合難易度、固定）＋NONE_MODEを
// 組み合わせた、レンズ（LensControl）の選択肢一覧を組み立てる。軸ごとの絞り込みは行わない
// （重み0の軸もレンズには選べる、公開軸を無条件で対象にする）。
// useAxisCatalog（hooks/useAxisCatalog.ts）が、実行時API取得結果・ビルド時静的
// フォールバックの両方からこの関数で同じ形の一覧を作る（axisLayers.ts:
// rampAxesFromCatalogAxes等と同じ片側importパターン）。
export function routeStyleModesFromCatalogAxes(axes: readonly AxisCatalogEntry[]): RouteStyleMode[] {
  const dynamicModes = axes.map(routeColorableModeFromAxis);
  return [...dynamicModes, DIFFICULTY_MODE, NONE_MODE];
}

/** 軸カタログを取得できていない間のモード一覧。難易度・「なし」は軸に依存しないため
 * 常に存在する。**ビルド時の軸の写しではなく、軸0件から同じ関数で導く。** */
export const ROUTE_STYLE_MODES_WITHOUT_AXES: readonly RouteStyleMode[] = routeStyleModesFromCatalogAxes([]);
