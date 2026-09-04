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

export interface Rectangle {
  minLon: number;
  maxLon: number;
  minLat: number;
  maxLat: number;
}

function cellRectangle(latitude: number, longitude: number, spacingDeg: number): Rectangle {
  const half = spacingDeg / 2;
  return { minLon: longitude - half, maxLon: longitude + half, minLat: latitude - half, maxLat: latitude + half };
}

function rectangleRing(rect: Rectangle): GeoJSON.Position[] {
  return [
    [rect.minLon, rect.minLat],
    [rect.maxLon, rect.minLat],
    [rect.maxLon, rect.maxLat],
    [rect.minLon, rect.maxLat],
    [rect.minLon, rect.minLat],
  ];
}

/** 矩形`cell`から矩形`hole`と重なる部分を取り除いた残りを、重ならない矩形の配列として返す
 * （軸に平行な矩形どうしの「引き算」を、外部ライブラリなしで最大4枚の帯[左右+中央上下]へ
 * 分解する標準的な手法）。`hole`が`cell`と全く重ならなければ`[cell]`を、`cell`を完全に
 * 覆っていれば`[]`を返す。`hole`は`cell`より大きくても小さくてもよい（重なった部分だけを
 * 引く）。 */
export function subtractRectangle(cell: Rectangle, hole: Rectangle): Rectangle[] {
  const ixMin = Math.max(cell.minLon, hole.minLon);
  const ixMax = Math.min(cell.maxLon, hole.maxLon);
  const iyMin = Math.max(cell.minLat, hole.minLat);
  const iyMax = Math.min(cell.maxLat, hole.maxLat);
  if (ixMin >= ixMax || iyMin >= iyMax) return [cell];
  const pieces: Rectangle[] = [];
  if (ixMin > cell.minLon) pieces.push({ minLon: cell.minLon, maxLon: ixMin, minLat: cell.minLat, maxLat: cell.maxLat });
  if (ixMax < cell.maxLon) pieces.push({ minLon: ixMax, maxLon: cell.maxLon, minLat: cell.minLat, maxLat: cell.maxLat });
  if (iyMax < cell.maxLat) pieces.push({ minLon: ixMin, maxLon: ixMax, minLat: iyMax, maxLat: cell.maxLat });
  if (iyMin > cell.minLat) pieces.push({ minLon: ixMin, maxLon: ixMax, minLat: cell.minLat, maxLat: iyMin });
  return pieces;
}

/** 詳細格子（`detailGrid`）の実際のカバー範囲を、返ってきた点群の外接矩形を
 * `detailSpacingDeg`半分ぶん外側へ広げた矩形（各詳細格子点自身のセルぶんの余白）として
 * 求める。`detailGrid`が空（詳細格子未取得・ズームアウト時）なら`null`を返す。 */
function detailCoverageBounds(detailGrid: readonly WindGridPoint[], detailSpacingDeg: number): Rectangle | null {
  if (detailGrid.length === 0) return null;
  const half = detailSpacingDeg / 2;
  return {
    minLat: Math.min(...detailGrid.map((p) => p.latitude)) - half,
    maxLat: Math.max(...detailGrid.map((p) => p.latitude)) + half,
    minLon: Math.min(...detailGrid.map((p) => p.longitude)) - half,
    maxLon: Math.max(...detailGrid.map((p) => p.longitude)) + half,
  };
}

/** 粗い格子（`windGrid`、関東本土全域を常時カバー）から、詳細格子（`detailGrid`）と
 * 重なるgridFillセルを作る（改善計画T515）。粗い格子セルと詳細格子セルを同じ場所へ両方
 * 重ねて描画すると、半透明のfill-opacityが二重に重なって色が不自然に濃くなり、凡例の色と
 * 対応が取れなくなる（ユーザー報告「色が二重に重なると、他の凡例と色の区別がつきにくく
 * なり、ユーザー体験としても違和感がある。割と致命的」）ため、点単位の除外ではなく
 * **幾何学的に重なった部分だけを切り取る**（`subtractRectangle`）。1つの粗いセルが
 * 詳細格子のカバー範囲と部分的にしか重ならない場合、残った部分（最大4枚の矩形）を別々の
 * Featureとして描画するため、1粗格子点が0〜4個のFeatureに対応することがある（全部が
 * 重なりの外なら1個そのまま、全部が重なりの内なら0個）。判定に格子点の中心座標だけを
 * 使う近傍判定ではなくセル自体の矩形差分を使うため、詳細格子のカバー範囲が粗いセルより
 * ずっと小さくても、粗いセルのうち実際にカバーされていない部分だけが正しく残る
 * （詳細格子の取得範囲自体はズームに応じた間隔のまま変更しないため、ズームインしたときの
 * 細かい表現[T185]はそのまま維持される）。`detailGrid`が空ならフィルタせず全セルを
 * そのまま返す。 */
export function windPenaltyCoarseGridToClippedFeatureCollection(
  coarseGrid: readonly WindGridPoint[],
  detailGrid: readonly WindGridPoint[],
  frameIndex: number,
  bearingDeg: number,
  coarseSpacingDeg: number,
  detailSpacingDeg: number
): GeoJSON.FeatureCollection<GeoJSON.Polygon, WindPenaltyGridCellProperties> {
  const detailBounds = detailCoverageBounds(detailGrid, detailSpacingDeg);
  const features: GeoJSON.Feature<GeoJSON.Polygon, WindPenaltyGridCellProperties>[] = [];
  for (const point of coarseGrid) {
    const speed = point.wind_speed_ms[frameIndex];
    const direction = point.wind_direction_deg[frameIndex];
    if (speed == null || direction == null) continue;
    const cell = cellRectangle(point.latitude, point.longitude, coarseSpacingDeg);
    const pieces = detailBounds ? subtractRectangle(cell, detailBounds) : [cell];
    const properties: WindPenaltyGridCellProperties = { windPenalty: windPenalty(speed, direction, bearingDeg) };
    for (const piece of pieces) {
      features.push({ type: "Feature", geometry: { type: "Polygon", coordinates: [rectangleRing(piece)] }, properties });
    }
  }
  return { type: "FeatureCollection", features };
}

/** wind_penalty（["get","windPenalty"]）を色へ変換するMapLibre fill-color式。評価軸グループ
 * （windAxisLayer.ts: windAxisColorExpression、feature-state経由）と同じ配色・しきい値の
 * 組み立てロジック（buildWindPenaltyColorExpression）を共有する——環境（面）・評価軸（線）は
 * 同じ[時刻,向き]入力を共有するという契約（T400.md「2.」節）に加え、色の意味も揃えることで
 * 両者を見比べやすくする。feature-state版と異なり、こちらはgeojson sourceのプロパティを
 * 直接["get",...]で読む。boundariesは省略時ビルド時既定値（WIND_AXIS_THRESHOLDS、
 * buildWindPenaltyColorExpression参照）。評価軸グループ側（windAxisColorExpression）と
 * 同じく軸スタジオのdisplay_thresholds_overrideを受け取り、「評価軸・環境グループで色の
 * 意味を揃える」契約を満たす。 */
export function windPenaltyFillColorExpression(boundaries?: readonly number[]): unknown[] {
  return buildWindPenaltyColorExpression(["get", "windPenalty"], boundaries);
}
