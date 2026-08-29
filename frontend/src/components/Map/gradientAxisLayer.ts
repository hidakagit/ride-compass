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
  COLOR_UP_MILD,
  COLOR_UP_STEEP,
  GRADIENT_BOUNDARIES,
  GRADIENT_COLOR_FLAT,
  GRADIENT_COLOR_HARD,
} from "./routeStyleModes";

/** setFeatureStateで差し込む状態キー（MapView.tsx側もこの値を使う、片側import）。 */
export const GRADIENT_AXIS_FEATURE_STATE_KEY = "gradientValue";

/** gradient_percent（符号付き%、正=登り・負=下り）を色へ変換するMapLibre expressionを
 * 組み立てる共通ロジック。値の取得元（feature-state or geojsonプロパティ）だけが呼び出し側で
 * 異なる——評価軸グループ（gradientAxisColorExpression、feature-state経由）と環境グループの
 * gridFill（gradientGridFill.ts、["get",...]経由）が同じ配色・しきい値を共有するという契約
 * （T400.md「2.」節）をコード上でも1箇所に集約する。ルート確定後の色分け
 * （routeStyleModes.ts: STATIC_MODESの"gradient"）とも同じ配色・しきい値
 * （GRADIENT_BOUNDARIES）を共有し、ルートの有無によらず同じ色の意味で見比べられるようにする
 * （routeStyleModes.tsのGRADIENT_BOUNDARIESコメント参照）。値が無い地物（まだフェッチして
 * いない等）はCOLOR_NO_DATA（灰色）にする。 */
export function buildGradientColorExpression(valueExpression: unknown[]): unknown[] {
  const colorExpression: unknown[] = ["step", valueExpression, COLOR_DOWNHILL];
  const colors = [GRADIENT_COLOR_FLAT, COLOR_UP_MILD, COLOR_UP_STEEP, GRADIENT_COLOR_HARD];
  GRADIENT_BOUNDARIES.forEach((boundary, index) => {
    colorExpression.push(boundary, colors[index]);
  });
  return ["case", ["==", valueExpression, null], COLOR_NO_DATA, colorExpression];
}

/** gradient値のfeature-state値を色へ変換するMapLibre expression。["feature-state", key]は
 * 該当キーが未設定のfeatureに対しnullを返す（MapLibreの仕様）。 */
export function gradientAxisColorExpression(): unknown[] {
  return buildGradientColorExpression(["feature-state", GRADIENT_AXIS_FEATURE_STATE_KEY]);
}
