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

/** wind_penalty（["get","windPenalty"]）を色へ変換するMapLibre fill-color式。評価軸グループ
 * （windAxisLayer.ts: windAxisColorExpression、feature-state経由）と同じ配色・しきい値の
 * 組み立てロジック（buildWindPenaltyColorExpression）を共有する——環境（面）・評価軸（線）は
 * 同じ[時刻,向き]入力を共有するという契約（T400.md「2.」節）に加え、色の意味も揃えることで
 * 両者を見比べやすくする。feature-state版と異なり、こちらはgeojson sourceのプロパティを
 * 直接["get",...]で読む。 */
export function windPenaltyFillColorExpression(): unknown[] {
  return buildWindPenaltyColorExpression(["get", "windPenalty"]);
}
