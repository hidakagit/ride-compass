// way_id→勾配（effective_gradient）配信層（改善計画T423、docs/tasks/T400.md「2. 動的要素…の
// 二重表現」節）のMapLibre側純粋ロジック。「評価軸」グループとしての勾配（軸スタジオが作る
// 他の軸と同じく道路そのものを線で塗る表示）の基盤——windAxisLayer.tsと同型だが、値がway単位で
// 異なる点が風とは違う（T423の重要な注意点: 勾配は道路自身の向きが本質的に必要な材料）。
//
// タイル座標計算・複数タイル分の応答統合はdynamicWayValues.ts（改善計画T411の実施）を
// windAxisLayer.tsと共有する。実際のfetch（services/regionApi.ts: fetchDynamicWayValues）・
// 状態管理（hooks/useDynamicWayValues.ts）・DOM/MapLibre操作（MapView.tsx）も同じ共通部品を
// 使う——このファイルには勾配固有の配色・しきい値・feature-stateキーだけを持つ。

import {
  COLOR_DOWNHILL,
  COLOR_NO_DATA,
  GRADIENT_BOUNDARIES,
  GRADIENT_COLOR_HARD,
  interpolateColors,
} from "./routeStyleModes";
import { buildRangeLegendBands, type MapColorLegendBand } from "./mapColorLegend";

/** setFeatureStateで差し込む状態キー（MapView.tsx側もこの値を使う、片側import）。 */
export const GRADIENT_AXIS_FEATURE_STATE_KEY = "gradientValue";

/** gradient_percent（符号付き%、正=登り・負=下り）を色へ変換するMapLibre expressionを
 * 組み立てる共通ロジック。値の取得元（feature-state or geojsonプロパティ）だけが呼び出し側で
 * 異なる——評価軸グループ（gradientAxisColorExpression、feature-state経由）と環境グループの
 * gridFill（gradientGridFill.ts、["get",...]経由）が同じ配色・しきい値を共有するという契約
 * （T400.md「2.」節）をコード上でも1箇所に集約する。ルート確定後の色分け
 * （routeStyleModes.ts: routeColorableModeFromAxisの符号付き経路）とも同じ配色・しきい値を
 * 共有し、ルートの有無によらず同じ色の意味で見比べられるようにする。改善計画T440:
 * boundariesは軸スタジオのdisplay_thresholds_override由来（未指定時はGRADIENT_BOUNDARIES）
 * で、要素数に関わらず動作する（interpolateColorsが段階数ぶんの色を自動生成するため、
 * 固定4色の配列を持たない）。値が無い地物（まだフェッチしていない等）はCOLOR_NO_DATA
 * （灰色）にする。 */
export function buildGradientColorExpression(
  valueExpression: unknown[],
  boundaries: readonly number[] = GRADIENT_BOUNDARIES
): unknown[] {
  const colors = interpolateColors(COLOR_DOWNHILL, GRADIENT_COLOR_HARD, boundaries.length + 1);
  const colorExpression: unknown[] = ["step", valueExpression, colors[0]];
  boundaries.forEach((boundary, index) => {
    colorExpression.push(boundary, colors[index + 1]);
  });
  return ["case", ["==", valueExpression, null], COLOR_NO_DATA, colorExpression];
}

/** gradient値のfeature-state値を色へ変換するMapLibre expression。["feature-state", key]は
 * 該当キーが未設定のfeatureに対しnullを返す（MapLibreの仕様）。boundariesは省略時
 * GRADIENT_BOUNDARIES（改善計画T440、buildGradientColorExpression参照）。 */
export function gradientAxisColorExpression(boundaries?: readonly number[]): unknown[] {
  return buildGradientColorExpression(["feature-state", GRADIENT_AXIS_FEATURE_STATE_KEY], boundaries);
}

/** 地図上の色分け凡例（ユーザー要望2026-08-31、mapColorLegend.ts冒頭コメント参照）。
 * buildGradientColorExpressionと同じ配色・しきい値（COLOR_DOWNHILL→GRADIENT_COLOR_HARD、
 * 未指定時GRADIENT_BOUNDARIES）から段階ラベル付きの凡例を組み立てる。値がgradient_percent
 * （符号付き%）のため単位は"%"。改善計画T513: windAxisLegendと同じく、段階ごとの体感
 * ラベルは軸スタジオのdisplay_band_labels_override（page.tsx経由）から任意で渡せる。
 * labelsの要素数がboundaries.length+1と一致する間だけ数値レンジの前に添える。 */
export function gradientAxisLegend(
  boundaries: readonly number[] = GRADIENT_BOUNDARIES,
  labels?: readonly string[]
): MapColorLegendBand[] {
  const colors = interpolateColors(COLOR_DOWNHILL, GRADIENT_COLOR_HARD, boundaries.length + 1);
  const bandCount = boundaries.length + 1;
  return buildRangeLegendBands(boundaries, colors, "%", labels && labels.length === bandCount ? labels : undefined);
}
