// ルートの線の色分けのモード（レンズ）。値はルートを作ったときに計算済みの区間（segments）が持ち、切り替えは
// MapLibreの色の式・絞り込みの式を差し替えるだけ。軸ごとのモードは公開軸から作り、総合難易度と「なし」だけが固定。

import palette from "@/types/generated/palette.json";
import type { LegendEntry } from "./legendFilter";
import { bandLabelsForBandCount, buildRangeLegendBands, LEGEND_NO_DATA_KEY } from "./mapColorLegend";
import type { AxisCatalogEntry } from "@/types/route";
import { bandColorsFor, COLOR_NO_DATA, DEFAULT_DIFFICULTY_BOUNDARIES, type MapValueKind } from "./valueScale";

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

// 段（凡例）から色の式と絞り込み付きの凡例を組む。`boundaries[i]`は段iとi+1の境界。区間の値にはnullが明示的に入り、
// to-numberはnullを0にするため、null（データなし）を先に分ける。`valueExpression`は入れ子のプロパティも指せる
// （例: `["get", <軸id>, ["get", "axis_difficulties"]]`）。
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

// 段の数は境界（軸カタログの`map_value_thresholds`）の数で決まり、ラベルは境界の数字から作る（しきい値を変えても一致する）。
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
  const labels = bandLabelsForBandCount(bandLabels, boundaries.length + 1);
  const steps = buildRangeLegendBands(boundaries, bandColorsFor(kind, boundaries), unit, labels);
  return {
    id,
    label,
    ...buildSteppedMode(valueExpression, steps, boundaries),
  };
}

// 公開軸1本のモード。塗る値の種類・単位・しきい値はbackendが決め、ルート前の専用配信の塗りと同じ尺度・配色になる。
function routeColorableModeFromAxis(axis: AxisCatalogEntry): RouteStyleMode {
  const kind: MapValueKind = axis.map_value_kind;
  const boundaries = axis.map_value_thresholds ?? DEFAULT_DIFFICULTY_BOUNDARIES;
  // backendは`map_value_kind`が`signed_material`になる条件としてterms 1件を要求するが
  // （domain/dynamic_way_values.py）、その不変条件はカタログのJSONには現れない。
  // 材料が引けないときは難易度モードへ倒す（塗れないより、軸の難易度で塗る方が近い）。
  const signedMaterial = axis.shape.kind === "breakpoint_linear" ? axis.shape.terms[0]?.material : undefined;
  if (kind === "signed_material" && signedMaterial) {
    return buildRangeSteppedMode({
      id: axis.axis_id,
      label: axis.label,
      valueExpression: ["get", signedMaterial, ["get", "material_values"]],
      kind,
      boundaries,
      unit: axis.map_value_unit,
      bandLabels: axis.display_band_labels_override,
    });
  }
  return buildRangeSteppedMode({
    id: axis.axis_id,
    label: `${axis.label}の影響`,
    valueExpression: ["get", axis.axis_id, ["get", "axis_difficulties"]],
    kind: "difficulty",
    boundaries,
    unit: axis.map_value_unit,
    bandLabels: axis.display_band_labels_override,
  });
}

// 総合難易度（全軸を重みで合成した0-100）。特定の軸に紐づかない固定のモード。
const DIFFICULTY_MODE: RouteStyleMode = buildRangeSteppedMode({
  id: LENS_DIFFICULTY_ID,
  label: "総合難易度",
  valueExpression: ["get", "difficulty"],
  kind: "difficulty",
  boundaries: DEFAULT_DIFFICULTY_BOUNDARIES,
  unit: "",
});

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

/** レンズの選択肢: 公開軸すべて（重みが0の軸も選べる）＋総合難易度＋「なし」。 */
export function routeStyleModesFromCatalogAxes(axes: readonly AxisCatalogEntry[]): RouteStyleMode[] {
  const dynamicModes = axes.map(routeColorableModeFromAxis);
  return [...dynamicModes, DIFFICULTY_MODE, NONE_MODE];
}

/** 軸カタログを取得できていない間のモード一覧。難易度・「なし」は軸に依存しないため
 * 常に存在する。**ビルド時の軸の写しではなく、軸0件から同じ関数で導く。** */
export const ROUTE_STYLE_MODES_WITHOUT_AXES: readonly RouteStyleMode[] = routeStyleModesFromCatalogAxes([]);
