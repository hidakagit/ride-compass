// フィーチャー→動的値配信層（風・勾配）の材料非依存な共通ロジック。「評価軸」グループとして
// 動的＋向きあり材料を道路そのものを線で塗る表示にする際、どの材料でも共通して必要になる
// タイル座標計算・複数タイル分の応答統合をここへ集約する。材料固有の値（配色・しきい値・
// setFeatureStateキー）はdedicatedWayValueLayer.tsが軸カタログの宣言から組み立てる
// （このファイルはMapLibreの色・feature-state概念を一切知らない）。

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

/** XYZタイルの経緯度範囲を求める（backend/app/domain/region.py: tile_bounds_lonlatのJS版）。
 * 面表示のセル形状を組み立てるために使う。 */
export function tileBoundsLonLat(
  z: number,
  x: number,
  y: number,
): { west: number; south: number; east: number; north: number } {
  const n = 2 ** z;
  const west = (x / n) * 360 - 180;
  const east = ((x + 1) / n) * 360 - 180;
  const northRad = Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n)));
  const southRad = Math.atan(Math.sinh(Math.PI * (1 - (2 * (y + 1)) / n)));
  return { west, east, north: (northRad * 180) / Math.PI, south: (southRad * 180) / Math.PI };
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
/** 道路タイルを引くズーム。地図のズームをタイルが存在する範囲へ丸める。 */
export function roadTileZoom(zoom: number, minZoom: number, maxZoom: number): number {
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

/** 複数タイルぶんの{feature_key: 値}応答を1つのMapへ統合する。同じ鍵が隣接タイルへ跨って
 * 複数回現れても値は同じはず（backend側のキャッシュがタイル単位のため）だが、念のため
 * 後勝ちにする。
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
