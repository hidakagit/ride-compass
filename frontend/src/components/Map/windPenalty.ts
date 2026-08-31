// 環境グループの風penalty gridFill面表示（改善計画T414、docs/tasks/T400.md「2. 動的要素…は
// 状態（ルートの有無）に応じてパラメータの出所と塗る対象が変わる」節）。
//
// ルート未確定時、環境グループ（面）と評価軸グループ（線、windAxisLayer.ts）は同じ
// ユーザー指定[時刻,向き]を共有する。評価軸グループはbackend（wind_way_service.py）が
// wind_penaltyを計算するが、環境グループのgridFillは既にブラウザへ届いている風グリッド
// （useWeatherGrid.ts: effectiveGrid、風の矢印windVectorと共有のフェッチ）から直接計算できる
// ため、追加のAPI呼び出しは不要——backend/app/domain/wind.py: WindCalculator.wind_penaltyの
// JS移植（windPenalty関数）をこのファイルが持つ。
//
// dynamicWeather.ts: gridCellRing・precipitationNowcast.ts: precipitationGridToCell
// FeatureCollectionと同じ「格子点を中心とする正方形セルのFeatureCollectionを作る」パターンを
// 踏襲する。

import type { WindGridPoint } from "@/types/weather";
import { gridCellRing, gridToFeatureCollection } from "./dynamicWeather";
import { buildWindPenaltyColorExpression } from "./windAxisLayer";

/** 走行方位と風向風速から、走行への風の影響（ペナルティ）を計算する。backend/app/domain/
 * wind.py: WindCalculator.wind_penaltyの純粋なJS移植（正の値=向かい風、負の値=追い風）。
 * 二重実装のため、`test_wind_penalty_matches_backend_formula`（windPenalty.test.ts）で
 * 既知の入出力ペアを両実装間でドリフト検知する。 */
export function windPenalty(windSpeedMs: number, windDirectionDeg: number, travelBearingDeg: number): number {
  const diffRad = ((windDirectionDeg - travelBearingDeg) * Math.PI) / 180;
  return windSpeedMs * Math.cos(diffRad);
}

export interface WindPenaltyGridCellProperties {
  windPenalty: number;
}

/** grid（風と共通の格子点マップ）のframeIndex番目の時刻ぶんの風向風速から、bearingDeg
 * （ユーザー指定の走行方位、全格子点共通）に対するwind_penaltyを求め、各格子点を中心とする
 * 1辺spacingDegの正方形セル（gridCellRing）のFeatureCollectionへ変換する。frameIndexが
 * 範囲外、または値が欠損している格子点はスキップする（precipitationGridToCellFeature
 * Collectionと同じ「1点の欠損で全体を落とさない」方針）。 */
export function windPenaltyGridToCellFeatureCollection(
  grid: readonly WindGridPoint[],
  frameIndex: number,
  bearingDeg: number,
  spacingDeg: number
): GeoJSON.FeatureCollection<GeoJSON.Polygon, WindPenaltyGridCellProperties> {
  return gridToFeatureCollection(
    grid,
    (point) => {
      const speed = point.wind_speed_ms[frameIndex];
      const direction = point.wind_direction_deg[frameIndex];
      return speed == null || direction == null ? null : ({ speed, direction } as const);
    },
    (point, { speed, direction }) => ({
      type: "Feature",
      geometry: { type: "Polygon", coordinates: [gridCellRing(point.latitude, point.longitude, spacingDeg)] },
      properties: { windPenalty: windPenalty(speed, direction, bearingDeg) },
    })
  );
}

/** 粗い格子（`windGrid`、関東本土全域を常時カバー）のうち、詳細格子（`detailGrid`）が
 * 既にカバーしている範囲の点を除いた配列を返す（実機報告2026-08-31「画面の右端が塗られる
 * こともあるが、境界に色の段差[濃さの違い]が見える」）。粗い格子セルと詳細格子セルを
 * 同じ範囲へ両方重ねて描画すると、半透明のfill-opacityが二重に重なって詳細格子の範囲だけ
 * 不自然に濃くなる（詳細格子1枚のopacity＝X、粗い格子1枚のopacity＝Xだとしても、両方
 * 重なった範囲は1-(1-X)^2で単純な合算より濃く見える）。詳細格子の点集合のバウンディング
 * ボックス（`detailSpacingDeg`ぶん外側へ余裕を持たせ、詳細格子セルの外周ぎりぎりまで
 * 確実にカバーする）に入る粗い格子点を除外することで、2枚が同じ場所を重ねて塗る状態を
 * 無くし、境界を単一のシームだけに抑える（値そのものの違いによる色の段差は、格子の解像度が
 * 異なる以上残る。実測ではopacityの二重重ねによる濃淡差の方が支配的だった）。
 * `detailGrid`が空（詳細格子未取得・ズームアウト時）ならフィルタせず全点を返す。 */
export function coarseGridPointsOutsideDetailBounds(
  coarseGrid: readonly WindGridPoint[],
  detailGrid: readonly WindGridPoint[],
  detailSpacingDeg: number
): WindGridPoint[] {
  if (detailGrid.length === 0) return coarseGrid.slice();
  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLon = Infinity;
  let maxLon = -Infinity;
  for (const point of detailGrid) {
    if (point.latitude < minLat) minLat = point.latitude;
    if (point.latitude > maxLat) maxLat = point.latitude;
    if (point.longitude < minLon) minLon = point.longitude;
    if (point.longitude > maxLon) maxLon = point.longitude;
  }
  const pad = detailSpacingDeg / 2;
  minLat -= pad;
  maxLat += pad;
  minLon -= pad;
  maxLon += pad;
  return coarseGrid.filter(
    (point) =>
      point.latitude < minLat || point.latitude > maxLat || point.longitude < minLon || point.longitude > maxLon
  );
}

/** wind_penalty（["get","windPenalty"]）を色へ変換するMapLibre fill-color式。評価軸グループ
 * （windAxisLayer.ts: windAxisColorExpression、feature-state経由）と同じ配色・しきい値の
 * 組み立てロジック（buildWindPenaltyColorExpression）を共有する——環境（面）・評価軸（線）は
 * 同じ[時刻,向き]入力を共有するという契約（T400.md「2.」節）に加え、色の意味も揃えることで
 * 両者を見比べやすくする。feature-state版と異なり、こちらはgeojson sourceのプロパティを
 * 直接["get",...]で読む。boundariesは省略時ビルド時既定値（WIND_AXIS_THRESHOLDS、
 * buildWindPenaltyColorExpression参照）——改善計画T473で評価軸グループ側
 * （windAxisColorExpression）と同じく軸スタジオのdisplay_thresholds_overrideを受け取れる
 * ようにし、「評価軸・環境グループで色の意味を揃える」契約を実際に満たすようにした
 * （以前はこの関数を引数無しで呼んでおり、環境グループだけ配線から取り残されていた）。 */
export function windPenaltyFillColorExpression(boundaries?: readonly number[]): unknown[] {
  return buildWindPenaltyColorExpression(["get", "windPenalty"], boundaries);
}
