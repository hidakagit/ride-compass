// way_id→wind_penalty配信層（改善計画T405、docs/tasks/T400.md「2. 動的要素…の二重表現」節）
// のMapLibre側純粋ロジック。「評価軸」グループとしての風（軸スタジオが作る他の軸と同じく
// 道路そのものを線で塗る表示）の基盤——ただし他のramp軸（axisLayers.ts）と違い、値がタイルへ
// 焼き込まれておらず、MapLibreのsetFeatureStateで別経路（新設API）から取得した値を後から
// 地物へ差し込む点が異なる。
//
// windLayer.ts/precipitationNowcast.tsと同型の分離方針: 実際のfetch（services/regionApi.ts:
// fetchWindWayPenalties）・状態管理（hooks/useWindAxisPenalties.ts）・DOM/MapLibre操作
// （MapView.tsx: map.setFeatureState呼び出し）は別ファイルが持ち、このファイルはDOM/
// MapLibreインスタンスを一切知らない純粋関数のみを持つ。

import { COLOR_UNKNOWN, rampColorForBand } from "./axisLayers";
import type { MapViewport } from "./windLayer";

export interface TileXY {
  z: number;
  x: number;
  y: number;
}

// Web Mercatorで表現できる緯度の限界（backend/app/domain/region.py: _MAX_MERCATOR_LATITUDEと
// 同じ値）。クランプしないとMath.log(タンジェントが負・0)がNaN/Infinityになりうる。
const MAX_MERCATOR_LATITUDE = 85.05112878;

/** 緯度経度からそれを含むXYZタイルのx,yを求める（backend/app/domain/region.py:
 * _lonlat_to_tile_indexのJS版）。 */
function lonLatToTileIndex(lon: number, lat: number, z: number): [number, number] {
  const n = 2 ** z;
  const x = Math.floor(((lon + 180) / 360) * n);
  const clampedLat = Math.max(-MAX_MERCATOR_LATITUDE, Math.min(lat, MAX_MERCATOR_LATITUDE));
  const latRad = (clampedLat * Math.PI) / 180;
  const y = Math.floor(((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n);
  return [x, y];
}

// 1回のフェッチで要求するタイル数の上限（安全弁）。ズームはminZoom〜maxZoomへクランプする
// ため、road-surface-tiles同様ブラウザ1画面ぶんのビューポートで通常この上限に達することは
// ない想定（極端に広いウィンドウ・低ズームでの防御的な上限）。
const MAX_TILES_PER_FETCH = 64;

/** 現在のビューポートを覆う道路タイル（road-surface-tilesと同じXYZ座標系）の一覧を返す。
 * ズームはminZoom〜maxZoomへクランプする（road-surface-tilesのvector source自身がminzoom/
 * maxzoom外はタイルを要求しないのと同じ理屈。backend/app/domain/region.py:
 * tiles_covering_bboxのJS版だが、呼び出し側がビューポートの実ズーム値をそのまま渡す点が
 * 異なる——サーバ側はz/x/y個別の物理タイル座標で完結するが、こちらは「今フロントに見えている
 * ズーム」から「実際に道路タイルが読み込まれるであろうズーム」を逆算する必要があるため）。 */
export function tilesCoveringViewport(viewport: MapViewport, minZoom: number, maxZoom: number): TileXY[] {
  const z = Math.min(maxZoom, Math.max(minZoom, Math.floor(viewport.zoom)));
  const n = 2 ** z;
  const [xStart, yStart] = lonLatToTileIndex(viewport.west, viewport.north, z);
  const [xEnd, yEnd] = lonLatToTileIndex(viewport.east, viewport.south, z);
  const xs = [Math.max(0, Math.min(xStart, n - 1)), Math.max(0, Math.min(xEnd, n - 1))].sort((a, b) => a - b);
  const ys = [Math.max(0, Math.min(yStart, n - 1)), Math.max(0, Math.min(yEnd, n - 1))].sort((a, b) => a - b);
  const tiles: TileXY[] = [];
  for (let x = xs[0]; x <= xs[1]; x++) {
    for (let y = ys[0]; y <= ys[1]; y++) {
      tiles.push({ z, x, y });
      if (tiles.length >= MAX_TILES_PER_FETCH) return tiles;
    }
  }
  return tiles;
}

/** 複数タイルぶんの{way_id: wind_penalty}応答（JSONオブジェクトのキーは常に文字列）を、
 * way_id(number)キーのMapへ統合する。同じway_idが隣接タイルへ跨って複数回現れても値は
 * 同じはず（backend側のRedisキャッシュがway_id単位のため）だが、念のため後勝ちにする。 */
export function mergeWindWayPenalties(responses: readonly Record<string, number>[]): Map<number, number> {
  const merged = new Map<number, number>();
  for (const response of responses) {
    for (const [wayId, value] of Object.entries(response)) {
      merged.set(Number(wayId), value);
    }
  }
  return merged;
}

/** setFeatureStateで差し込む状態キー（MapView.tsx側もこの値を使う、片側import）。 */
export const WIND_AXIS_FEATURE_STATE_KEY = "windPenalty";

// wind_penalty（m/s、正=向かい風・負=追い風、backend/app/domain/wind.py: WindCalculator.
// wind_penalty参照）の色分けしきい値。5段階（RAMP_COLOR_ANCHORSの4色をrampColorForBandで
// 線形補間、axisLayers.ts参照）。±2m/sは体感し始める目安、±6m/sは強風域
// （windLayer.ts: WIND_SPEED_COLOR_STOPSのBf4上限相当）を大まかに踏襲した暫定値——他のramp軸
// と違い軸スタジオ・axis-catalogが持つthresholdsではない（このレイヤー自体が軸スタジオの
// 管理対象外の暫定チップという位置づけ、T405.mdのスコープはRedis配信層とsetFeatureState
// 連携の基盤でありUI・しきい値の作り込みはT406[パネル構成再編]以降の課題）。
export const WIND_AXIS_THRESHOLDS: readonly number[] = [-6, -2, 2, 6];

/** wind_penaltyのfeature-state値を色へ変換するMapLibre expression。値が無い地物
 * （まだフェッチしていない・その位置のway_idが応答に含まれなかった等）はCOLOR_UNKNOWN
 * （灰色、他のramp軸の「不明」表示と同じ色）にする。["feature-state", key]は該当キーが
 * 未設定のfeatureに対しnullを返す（MapLibreの仕様）。 */
export function windAxisColorExpression(): unknown[] {
  const value = ["feature-state", WIND_AXIS_FEATURE_STATE_KEY];
  const bandCount = WIND_AXIS_THRESHOLDS.length + 1;
  const stepExpression: unknown[] = ["step", value, rampColorForBand(0, bandCount)];
  WIND_AXIS_THRESHOLDS.forEach((threshold, index) => {
    stepExpression.push(threshold, rampColorForBand(index + 1, bandCount));
  });
  return ["case", ["==", value, null], COLOR_UNKNOWN, stepExpression];
}
