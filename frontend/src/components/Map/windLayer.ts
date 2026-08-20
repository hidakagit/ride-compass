// 風の格子点マップ（改善計画T178フォローアップ）のデータ層。DOM/MapLibreを一切知らない
// 純粋関数のみを持つ（precipitationNowcast.tsと同型）。実際のフェッチ・地図への反映は
// page.tsx/MapView.tsxが行う。
//
// 当初は`@openmeteo/weather-map-layer`（気象庁MSM由来、Open-Meteo配信のom://プロトコル）で
// 矢印を描画していたが、(1) ライブラリ本体・内部の.omファイルデコーダともGPL-2.0-onlyで
// GPLv2依存が避けられない、(2) 矢印の長さがライブラリ側でズームレベル依存に固定され自由に
// 表現できない、という2つの制約に実機で行き当たった。ユーザー判断（2026-08-20「自前実装案で
// 進めて」）により、既存のOpen-Meteo REST API経由の地点評価（weather_client.py:
// get_forecast_many、CC-BY-4.0・GPL無関係）と同じ仕組みでバックエンドが関東本土の固定格子点を
// サンプリングするAPI（GET /api/weather/wind-grid）を新設し、フロントはその結果を
// MapLibre標準のsymbolレイヤー（矢印アイコンを独自定義、向き・長さ・色すべて自由に設定可能）で
// 描画する方式へ切り替えた。

import type { WindGridPoint } from "@/types/weather";

/** grid[i].times[frameIndex]に対応する表示用フレーム。timesは全格子点で共通のはず
 * （同じforecast_days・timezoneで一括取得しているため）だが、念のため呼び出し元は
 * grid[0]?.timesを正としてスライダーへ渡す想定。 */

/** 現在時刻に最も近いフレームのindex。Open-Meteoのhourly.timeは午前0時始まりの配列
 * （実際の取得時刻が真夜中とは限らない）のため、降水ナウキャストのような単純な末尾/先頭
 * ではなく実際の時刻差で探す。空配列なら0。timesは"YYYY-MM-DDTHH:MM"形式のJST時刻文字列
 * （タイムゾーン情報を持たないため、パース時にJSTを明示する。parseJstTime参照）。 */
export function nearestFrameIndexToNow(times: readonly string[], now: Date = new Date()): number {
  if (times.length === 0) return 0;
  const nowMs = now.getTime();
  let bestIndex = 0;
  let bestDiffMs = Infinity;
  for (let i = 0; i < times.length; i++) {
    const diffMs = Math.abs(parseJstTime(times[i]).getTime() - nowMs);
    if (diffMs < bestDiffMs) {
      bestDiffMs = diffMs;
      bestIndex = i;
    }
  }
  return bestIndex;
}

/** "YYYY-MM-DDTHH:MM"（Open-Meteoのtimezone=Asia/Tokyo指定によるJST・オフセット無し表記）を
 * JSTとして解釈するDateへ変換する。オフセット無しのままDateへ渡すとブラウザのローカル
 * タイムゾーンとして解釈されてしまう（日本国外の閲覧環境で時刻がずれる）ため、明示的に
 * +09:00を付与する。下部バー2本の時刻連動（改善計画、実機フィードバック「同じ日時を
 * 示した状態で連動させ」）で、風スライダーのindexを共有の対象時刻へ変換するためpage.tsxからも
 * 使うのでexportしている。 */
export function parseJstTime(time: string): Date {
  return new Date(`${time}+09:00`);
}

/** ISO風の"YYYY-MM-DDTHH:MM"（JST）→ 表示用のJST時刻文字列。約48時間先まで日付をまたぐため
 * "M/D HH:mm"で日付も含める（precipitationNowcast.tsのformatNowcastFrameTimeは±60分で
 * 日付をまたがないため時刻のみ、こちらは異なる）。 */
export function formatWindFrameTime(time: string): string {
  const date = parseJstTime(time);
  const datePart = date.toLocaleDateString("ja-JP", { month: "numeric", day: "numeric", timeZone: "Asia/Tokyo" });
  const timePart = date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo" });
  return `${datePart} ${timePart}`;
}

export interface WindPointFeatureProperties {
  /** 風速（m/s） */
  speed: number;
  /** 矢印の向き（度、MapLibreのicon-rotate用に「風が吹いていく方向」＝気象学的な風向
   * （吹いてくる方向）+180した値。北=0、時計回り）。 */
  bearing: number;
}

/** grid（バックエンドから取得した格子点一覧）のframeIndex番目の時刻ぶんを、MapLibreの
 * GeoJSON sourceへそのまま渡せるFeatureCollectionへ変換する。frameIndexが範囲外、または
 * 値が欠損している格子点はスキップする（1点の欠損で全体を落とさない）。 */
export function windGridToFeatureCollection(
  grid: readonly WindGridPoint[],
  frameIndex: number
): GeoJSON.FeatureCollection<GeoJSON.Point, WindPointFeatureProperties> {
  const features: GeoJSON.Feature<GeoJSON.Point, WindPointFeatureProperties>[] = [];
  for (const point of grid) {
    const speed = point.wind_speed_ms[frameIndex];
    const direction = point.wind_direction_deg[frameIndex];
    if (speed == null || direction == null) continue;
    features.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: [point.longitude, point.latitude] },
      properties: { speed, bearing: (direction + 180) % 360 },
    });
  }
  return { type: "FeatureCollection", features };
}

// 格子間隔（度）。backend/app/domain/wind_grid.pyの同名定数（WIND_GRID_SPACING_DEG/
// WIND_GRID_DETAIL_SPACING_DEG）と値を合わせること。APIレスポンス自体には間隔情報が
// 含まれない（点の配列のみ）ため、フロント側でも同じ値を持つ必要がある。
export const WIND_GRID_SPACING_DEG = 0.1;
export const WIND_GRID_DETAIL_SPACING_DEG = 0.02;

export interface WindCellFeatureProperties {
  /** 風速（m/s）。矢印（WindPointFeatureProperties.speed）と同じ意味・同じ着色スケールで使う。 */
  speed: number;
}

/** grid各点を中心とする1辺spacingDegの正方形セルへ変換する（実機フィードバック「どの範囲の
 * 風向き・風速を示しているか分かりにくい」対応）。矢印は1点の値を示す記号だが、格子点は
 * 実際には周辺の面（隣の格子点までの範囲）を代表しているため、その範囲を薄い塗りで
 * 明示する。矢印と同じ色スケール（MapView.tsx側のfill-color）で塗ることで、
 * 「この矢印がこのセルの値」という対応が一目で分かるようにする。 */
export function windGridToCellFeatureCollection(
  grid: readonly WindGridPoint[],
  frameIndex: number,
  spacingDeg: number
): GeoJSON.FeatureCollection<GeoJSON.Polygon, WindCellFeatureProperties> {
  const half = spacingDeg / 2;
  const features: GeoJSON.Feature<GeoJSON.Polygon, WindCellFeatureProperties>[] = [];
  for (const point of grid) {
    const speed = point.wind_speed_ms[frameIndex];
    if (speed == null) continue;
    const { latitude: lat, longitude: lon } = point;
    features.push({
      type: "Feature",
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [lon - half, lat - half],
            [lon + half, lat - half],
            [lon + half, lat + half],
            [lon - half, lat + half],
            [lon - half, lat - half],
          ],
        ],
      },
      properties: { speed },
    });
  }
  return { type: "FeatureCollection", features };
}

export interface MapViewport {
  west: number;
  south: number;
  east: number;
  north: number;
  zoom: number;
}

export interface Bbox {
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
}

// 詳細格子（改善計画T180）を出す最低ズーム。これ未満は広域の粗い格子（既存のgetWindGrid）
// だけで足りると判断（狭い範囲を詳細に見るための機能のため）。
export const WIND_DETAIL_MIN_ZOOM = 10;
// 1回のリクエストで要求するbboxの最大幅・高さ（度）。ズーム10でも横長デスクトップの
// ビューポートは経度方向に2°を超えることがあり、そのままバックエンドへ渡すとdetail間隔
// （0.02度）ではWIND_GRID_DETAIL_MAX_POINTS（900、backend/app/domain/wind_grid.py）を
// 超えて400になる。ビューポート中心を基準にこの幅へクリップしてから要求する
// （0.5度四方なら0.02度間隔で最大26×26=676点、安全に収まる）。
const WIND_DETAIL_MAX_BBOX_SPAN_DEG = 0.5;

/** 現在のビューポートから、詳細格子APIへ渡すbboxを求める。ビューポートがクリップ幅より
 * 狭ければビューポートそのまま、広ければ中心を基準に最大幅へクリップする（上記コメント参照）。 */
export function clampWindDetailBbox(viewport: MapViewport): Bbox {
  const halfSpan = WIND_DETAIL_MAX_BBOX_SPAN_DEG / 2;
  const centerLon = (viewport.west + viewport.east) / 2;
  const centerLat = (viewport.south + viewport.north) / 2;
  return {
    minLon: Math.max(viewport.west, centerLon - halfSpan),
    minLat: Math.max(viewport.south, centerLat - halfSpan),
    maxLon: Math.min(viewport.east, centerLon + halfSpan),
    maxLat: Math.min(viewport.north, centerLat + halfSpan),
  };
}
