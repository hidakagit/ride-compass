// 専用way_id→値配信レイヤー（backend `GET /api/region/dynamic-way-values/{axis_id}/...`、
// `dedicated_way_value_layer=true`の軸）のMapLibre側純粋ロジック。ルート確定前に視界内の
// 全道路を、その軸の地図表示値（backendが軸定義から決める`map_value_kind`のスケール:
// 難易度0〜100、または符号付き材料生値）で線色分けする。他のramp軸（axisLayers.ts）と違い
// 値がタイルへ焼き込まれておらず、setFeatureStateで別経路から取得した値を後から地物へ
// 差し込む。軸ごとのファイル・定数は持たず、軸スタジオが配信するDedicatedWayValueDisplay
// （種類・単位・しきい値・段階ラベル）だけから色式と凡例を組み立てる。
//
// 実際のfetch（services/regionApi.ts: fetchDynamicWayValues）・状態管理
// （hooks/useDynamicWayValues.ts）・DOM/MapLibre操作（MapView.tsx: map.setFeatureState）は
// 別ファイルが持ち、このファイルはMapLibreインスタンスを一切知らない純粋関数のみを持つ。

import { buildRangeLegendBands, type MapColorLegendBand } from "./mapColorLegend";
import { bandColorsFor, buildSteppedColorExpression, valueScaleFor, type MapValueKind } from "./valueScale";

export type { TileXY } from "./dynamicWayValues";
export { tilesCoveringViewport, mergeDynamicWayValues } from "./dynamicWayValues";

/** 軸カタログ（GET /api/axis-catalog）から軸ごとに組み立てる表示宣言。しきい値・段階ラベルは
 * 軸スタジオのdisplay_thresholds_override / display_band_labels_override（未設定なら
 * 種類の既定値・数値レンジのみ）。 */
export interface DedicatedWayValueDisplay {
  kind: MapValueKind;
  unit: string;
  boundaries?: readonly number[] | null;
  bandLabels?: readonly string[] | null;
}

/** 軸カタログの取得前など表示宣言が無い場合の既定（難易度スケール、単位なし）。 */
export const DEFAULT_DEDICATED_WAY_VALUE_DISPLAY: DedicatedWayValueDisplay = { kind: "difficulty", unit: "" };

/** setFeatureStateで差し込む状態キー。同じ路面タイルソースの地物へ複数の軸が値を持つため
 * 軸idごとに異なるキーにする。 */
export function dedicatedWayValueFeatureStateKey(axisId: string): string {
  return `${axisId}Value`;
}

/** 値取得式（feature-state or geojsonプロパティ）を色へ変換するMapLibre expression。
 * 値の取得元だけが呼び出し側で異なり、評価軸グループの線（feature-state経由）と環境
 * グループの面（勾配gridFill、["get",...]経由）が同じ配色・しきい値を共有する。 */
export function buildDedicatedWayValueColorExpression(
  valueExpression: unknown[],
  display: DedicatedWayValueDisplay = DEFAULT_DEDICATED_WAY_VALUE_DISPLAY
): unknown[] {
  return buildSteppedColorExpression(valueExpression, display.kind, display.boundaries);
}

/** feature-state値を色へ変換するMapLibre expression。["feature-state", key]は該当キーが
 * 未設定のfeatureに対しnullを返す（MapLibreの仕様）。 */
export function dedicatedWayValueColorExpression(axisId: string, display?: DedicatedWayValueDisplay): unknown[] {
  return buildDedicatedWayValueColorExpression(["feature-state", dedicatedWayValueFeatureStateKey(axisId)], display);
}

/** 地図上の色分け凡例。色式と同じ配色・しきい値から段階ラベル付きの凡例を組み立てる。
 * 段階ラベル（bandLabels）は要素数が段階数と一致する間だけ数値レンジの前に添える
 * （不一致な保存データへの防御）。 */
export function dedicatedWayValueLegend(
  display: DedicatedWayValueDisplay = DEFAULT_DEDICATED_WAY_VALUE_DISPLAY
): MapColorLegendBand[] {
  const boundaries = display.boundaries ?? valueScaleFor(display.kind).defaultBoundaries;
  const colors = bandColorsFor(display.kind, boundaries);
  const labels = display.bandLabels && display.bandLabels.length === boundaries.length + 1 ? display.bandLabels : undefined;
  return buildRangeLegendBands(boundaries, colors, display.unit, labels);
}
