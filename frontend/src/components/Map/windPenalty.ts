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

/** 粗い格子（`windGrid`、関東本土全域を常時カバー）のうち、セル全体（1辺`coarseSpacingDeg`の
 * 正方形）が詳細格子（`detailGrid`）の実際のカバー範囲にすっぽり収まっている点だけを除いた
 * 配列を返す。粗い格子セルと詳細格子セルを同じ場所へ両方重ねて描画すると、半透明の
 * fill-opacityが二重に重なって詳細格子の範囲だけ不自然に濃くなるため、重複描画を避けたい。
 *
 * 詳細格子のカバー範囲は、実際に返ってきた点群の外接矩形を`detailSpacingDeg`半分ぶん
 * 外側へ広げたもの（各詳細格子点自身のセルぶんの余白）として求める。判定は粗い格子点の
 * 中心1点への近傍判定ではなく、セル全体（4隅すべて）がこの範囲へ収まっているかで行う——
 * 粗い格子1セル（`coarseSpacingDeg`）は詳細格子のカバー範囲（ズームインしたときの狭い
 * bbox、`clampWindDetailBbox`参照）よりずっと大きいことが多く、中心点だけを見る近傍判定
 * だと「中心が詳細格子のすぐ近くにある」というだけで、詳細格子が実際には覆っていない
 * セルの残り部分まで丸ごと除外してしまい、粗い・詳細のどちらも描画されない穴ができる
 * （実測: 詳細格子30点に対し粗い格子624点中623点が除外され、画面の大半が未カバーになる
 * 事例を確認）。セル全体の包含を見ることで、詳細格子のカバー範囲より大きい粗いセルは
 * 除外されず残る。`detailGrid`が空（詳細格子未取得・ズームアウト時）ならフィルタせず
 * 全点を返す。 */
export function coarseGridPointsOutsideDetailBounds(
  coarseGrid: readonly WindGridPoint[],
  detailGrid: readonly WindGridPoint[],
  coarseSpacingDeg: number,
  detailSpacingDeg: number
): WindGridPoint[] {
  if (detailGrid.length === 0) return coarseGrid.slice();
  const detailHalf = detailSpacingDeg / 2;
  const detailMinLat = Math.min(...detailGrid.map((p) => p.latitude)) - detailHalf;
  const detailMaxLat = Math.max(...detailGrid.map((p) => p.latitude)) + detailHalf;
  const detailMinLon = Math.min(...detailGrid.map((p) => p.longitude)) - detailHalf;
  const detailMaxLon = Math.max(...detailGrid.map((p) => p.longitude)) + detailHalf;
  const coarseHalf = coarseSpacingDeg / 2;
  return coarseGrid.filter((coarsePoint) => {
    const fullyCovered =
      coarsePoint.latitude - coarseHalf >= detailMinLat &&
      coarsePoint.latitude + coarseHalf <= detailMaxLat &&
      coarsePoint.longitude - coarseHalf >= detailMinLon &&
      coarsePoint.longitude + coarseHalf <= detailMaxLon;
    return !fullyCovered;
  });
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
