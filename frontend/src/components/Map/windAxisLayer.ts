// way_id→wind_penalty配信層（改善計画T405、docs/tasks/T400.md「2. 動的要素…の二重表現」節）
// のMapLibre側純粋ロジック。「評価軸」グループとしての風（軸スタジオが作る他の軸と同じく
// 道路そのものを線で塗る表示）の基盤——ただし他のramp軸（axisLayers.ts）と違い、値がタイルへ
// 焼き込まれておらず、MapLibreのsetFeatureStateで別経路（新設API）から取得した値を後から
// 地物へ差し込む点が異なる。
//
// windLayer.ts/precipitationNowcast.tsと同型の分離方針: 実際のfetch（services/regionApi.ts:
// fetchDynamicWayValues）・状態管理（hooks/useDynamicWayValues.ts）・DOM/MapLibre操作
// （MapView.tsx: map.setFeatureState呼び出し）は別ファイルが持ち、このファイルはDOM/
// MapLibreインスタンスを一切知らない純粋関数のみを持つ。
//
// 改善計画T423（T411の実施）: タイル座標計算・複数タイル分の応答統合という材料非依存の
// 部分はdynamicWayValues.tsへ抽出した（gradientAxisLayer.tsと共有）。このファイルには
// 風固有の配色・しきい値・feature-stateキーだけが残る。

import { COLOR_UNKNOWN, rampColorForBand } from "./axisLayers";

export type { TileXY } from "./dynamicWayValues";
export { tilesCoveringViewport, mergeDynamicWayValues } from "./dynamicWayValues";

/** setFeatureStateで差し込む状態キー（MapView.tsx側もこの値を使う、片側import）。 */
export const WIND_AXIS_FEATURE_STATE_KEY = "windPenalty";

// wind_penalty（m/s、正=向かい風・負=追い風、backend/app/domain/wind.py: WindCalculator.
// wind_penalty参照）の色分けしきい値の既定値。5段階（RAMP_COLOR_ANCHORSの4色をrampColorForBandで
// 線形補間、axisLayers.ts参照）。±2m/sは体感し始める目安、±6m/sは強風域
// （windLayer.ts: WIND_SPEED_COLOR_STOPSのBf4上限相当）を大まかに踏襲した暫定値。改善計画T473:
// 軸スタジオのaxis_definitions.display_thresholds_overrideは、wind/gradientいずれも
// page.tsx: dedicatedWayValueBoundaries（axisCatalog.axesから`dedicated_way_value_layer=true`
// の軸を横断的に抽出した汎用Map）経由でMapView.tsxへ渡る（以前はwindBoundaries/
// gradientBoundariesという軸ごとの別名propだった）。未設定時はこの既定値へフォールバックする。
export const WIND_AXIS_THRESHOLDS: readonly number[] = [-6, -2, 2, 6];

/** wind_penalty値（boundariesのしきい値・配色）を色へ変換するMapLibre expressionを
 * 組み立てる共通ロジック。値の取得元（feature-state or geojsonプロパティ）だけが呼び出し側で
 * 異なる——評価軸グループ（windAxisColorExpression、feature-state経由）と環境グループの
 * gridFill（windPenalty.ts: windPenaltyFillColorExpression、["get",...]経由）が同じ配色・
 * しきい値を共有するという契約（T400.md「2.」節）をコード上でも1箇所に集約する。値が無い地物
 * （まだフェッチしていない等）はCOLOR_UNKNOWN（灰色、他のramp軸の「不明」表示と同じ色）にする。 */
export function buildWindPenaltyColorExpression(
  valueExpression: unknown[],
  boundaries: readonly number[] = WIND_AXIS_THRESHOLDS
): unknown[] {
  const bandCount = boundaries.length + 1;
  const stepExpression: unknown[] = ["step", valueExpression, rampColorForBand(0, bandCount)];
  boundaries.forEach((threshold, index) => {
    stepExpression.push(threshold, rampColorForBand(index + 1, bandCount));
  });
  return ["case", ["==", valueExpression, null], COLOR_UNKNOWN, stepExpression];
}

/** wind_penaltyのfeature-state値を色へ変換するMapLibre expression。["feature-state", key]は
 * 該当キーが未設定のfeatureに対しnullを返す（MapLibreの仕様）。boundariesは省略時
 * WIND_AXIS_THRESHOLDS（改善計画T466、buildWindPenaltyColorExpression参照）。 */
export function windAxisColorExpression(boundaries?: readonly number[]): unknown[] {
  return buildWindPenaltyColorExpression(["feature-state", WIND_AXIS_FEATURE_STATE_KEY], boundaries);
}
