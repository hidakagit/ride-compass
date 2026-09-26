// 専用配信の値を取るタイルの座標と、複数タイルの応答の統合（軸によらない）。

import regionTileConfig from "@/types/generated/region-tile-config.json";

export interface TileXY {
  z: number;
  x: number;
  y: number;
}

// Web Mercatorで表せる緯度の限界。挟まないとlogがNaN/Infinityになりうる。
const MAX_MERCATOR_LATITUDE = regionTileConfig.max_mercator_latitude;

/** 緯度経度を含むXYZタイルのx,y。 */
function lonLatToTileIndex(lon: number, lat: number, z: number): [number, number] {
  const n = 2 ** z;
  const x = Math.floor(((lon + 180) / 360) * n);
  const clampedLat = Math.max(-MAX_MERCATOR_LATITUDE, Math.min(lat, MAX_MERCATOR_LATITUDE));
  const latRad = (clampedLat * Math.PI) / 180;
  const y = Math.floor(((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n);
  return [x, y];
}

// 1回に求めるタイルの数の上限（ズームは範囲へ丸めるので、ふつうの画面では届かない）。
const MAX_TILES_PER_FETCH = 64;

/** 道路タイルを引くズーム。地図のズームをタイルが存在する範囲へ丸める。 */
function roadTileZoom(zoom: number, minZoom: number, maxZoom: number): number {
  return Math.min(maxZoom, Math.max(minZoom, Math.floor(zoom)));
}

/** 指定した1点を含む道路タイル。**レンズが引いたのと同じタイルを指す**ため、ズームの
 * 丸め方はtilesCoveringViewportと共有する（ずれると同じ値がキャッシュにあっても引き直しになる）。 */
export function tileContainingLonLat(lon: number, lat: number, zoom: number, minZoom: number, maxZoom: number): TileXY {
  const z = roadTileZoom(zoom, minZoom, maxZoom);
  const n = 2 ** z;
  const [x, y] = lonLatToTileIndex(lon, lat, z);
  return { z, x: Math.max(0, Math.min(x, n - 1)), y: Math.max(0, Math.min(y, n - 1)) };
}

/** 表示範囲を覆う道路タイル。地図のズームから、道路タイルが実際に読まれるズームを求めて使う。 */
export function tilesCoveringViewport(
  viewport: { west: number; north: number; east: number; south: number; zoom: number },
  minZoom: number,
  maxZoom: number,
): TileXY[] {
  const z = roadTileZoom(viewport.zoom, minZoom, maxZoom);
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

/** 複数タイルの`{feature_key: 値}`を1つにする（隣のタイルに同じ鍵があれば後勝ち）。
 *
 * **鍵は文字列のまま扱う**。路面タイルの`feature_key`はズームによってway_idにも
 * edge_idにもなり（backendの`EDGE_UNIT_MIN_ZOOM`）、edge_idは数値ではない。数値へ
 * 変換すると`setFeatureState`のidがタイル側のfeature.idと一致せず、色が一切付かない。 */
export function mergeDynamicWayValues(responses: readonly Record<string, number>[]): Map<string, number> {
  const merged = new Map<string, number>();
  for (const response of responses) {
    for (const [featureKey, value] of Object.entries(response)) {
      merged.set(featureKey, value);
    }
  }
  return merged;
}
