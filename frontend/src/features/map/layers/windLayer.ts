// 風と降水が共有する格子の扱い（今より前の時刻を落とす・取り損ねた地点を補う・詳細格子の間隔と範囲）と、風の矢印。

import palette from "@/types/generated/palette.json";
import type { Bbox } from "@/services/weatherApi";
import weatherScales from "@/types/generated/weather-scales.json";
import { gridToFeatureCollection, type DynamicWeatherRenderPayload } from "@/features/map/layers/dynamicWeather";
import type { WindGridPoint } from "@/types/weather";
import windGridConfig from "@/types/generated/wind-grid-config.json";
import { parseJstLocalValue } from "@/lib/time";
import { buildRangeLegendBands, type MapColorLegendBand } from "@/lib/mapDisplay/mapColorLegend";

/** 格子を「今が属する1時間」以降へ切り詰める（取ってから時間が経つと先頭が過去になる）。「今」は最も近い時刻ではなく
 * 今以下で最も新しい時刻——最も近い時刻だと、正時を少し過ぎただけで今の1時間が消える。時刻の列は全点で共通。 */
export function trimWindGridToCurrentAndFuture(
  grid: readonly WindGridPoint[],
  now: Date = new Date(),
): WindGridPoint[] {
  if (grid.length === 0) return [];
  const times = grid[0].times;
  const nowMs = now.getTime();
  let startIndex = 0;
  for (let i = 0; i < times.length; i++) {
    if (parseJstLocalValue(times[i]).getTime() <= nowMs) startIndex = i;
  }
  if (startIndex === 0) return grid.slice();
  return grid.map((point) => ({
    ...point,
    times: point.times.slice(startIndex),
    wind_speed_ms: point.wind_speed_ms.slice(startIndex),
    wind_direction_deg: point.wind_direction_deg.slice(startIndex),
    precipitation_mm: point.precipitation_mm.slice(startIndex),
  }));
}

/** 新しい格子に、前回の格子のうち新しい方に無い地点を補う。backendは取れなかった地点を応答から除くので、取り直す
 * たびに欠ける地点が変わる——古い値が残る方が、地図に穴が開くよりよい。地点は緯度経度で見分ける。切り詰める前の
 * 格子を渡す（切り詰めた後は先頭の位置が取るたびにずれ、古い地点だけ添字の意味が食い違う）。 */
export function mergeWindGridKeepingStale(
  previous: readonly WindGridPoint[],
  next: readonly WindGridPoint[],
): WindGridPoint[] {
  const nextKeys = new Set(next.map((point) => `${point.latitude},${point.longitude}`));
  const staleCarryOver = previous.filter((point) => !nextKeys.has(`${point.latitude},${point.longitude}`));
  return [...next, ...staleCarryOver];
}

// 風速の段（帯の下限・色・呼び名）。段の決め方はbackendの宣言が持つ。
export const WIND_SPEED_COLOR_STOPS: readonly { speedMs: number; color: string; name: string }[] =
  weatherScales.wind_speed.map((stop) => ({ speedMs: stop.value, color: stop.color, name: stop.name }));

// この風速未満は無風として矢印を描かない。境はbackendの宣言が持つ。
export const WIND_CALM_THRESHOLD_MS = weatherScales.wind_calm_below_ms;

// 凡例の行は地図の段と1対1（束ねると、束ねた中の値が色見本と食い違う）。先頭に矢印を出さない無風の行を置く。
export const WIND_SPEED_LEGEND_LEVELS: readonly MapColorLegendBand[] = buildRangeLegendBands(
  [WIND_CALM_THRESHOLD_MS, ...WIND_SPEED_COLOR_STOPS.slice(1).map((stop) => stop.speedMs)],
  [palette.semantic.no_data, ...WIND_SPEED_COLOR_STOPS.map((stop) => stop.color)],
  "m/s",
  ["無風・矢印なし", ...WIND_SPEED_COLOR_STOPS.map((stop) => stop.name)],
);

interface WindPointFeatureProperties {
  /** 風速（m/s） */
  speed: number;
  /** 矢印の向き（度、北=0・時計回り）。風が吹いていく方向なので、気象の風向（吹いてくる方向）+180。 */
  bearing: number;
}

/** 格子の`index`番目の時刻の風を、格子点ごとの矢印（gridMark）にする。値の欠けた点は飛ばす。 */
export function windArrows(grid: readonly WindGridPoint[], index: number): DynamicWeatherRenderPayload {
  const geojson: GeoJSON.FeatureCollection<GeoJSON.Point, WindPointFeatureProperties> = gridToFeatureCollection(
    grid,
    (point) => {
      const speed = point.wind_speed_ms[index];
      const direction = point.wind_direction_deg[index];
      return speed == null || direction == null ? null : ({ speed, direction } as const);
    },
    (point, { speed, direction }) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [point.longitude, point.latitude] },
      properties: { speed, bearing: (direction + 180) % 360 },
    }),
  );
  return { kind: "gridMark", geojson };
}

// 格子の間隔（度）。応答は点の並びだけで間隔を持たないので、backendの宣言から取る。
export const WIND_GRID_SPACING_DEG = windGridConfig.spacing_deg;

export interface MapViewport {
  west: number;
  south: number;
  east: number;
  north: number;
  zoom: number;
}

// 詳細格子を取る最低のズーム（これ未満は広域の粗い格子で足りる）。
export const WIND_DETAIL_MIN_ZOOM = 10;

// ズームに応じた詳細格子の間隔。面で塗るセルは1点が受け持つ実面積なので、表示を縮めても隙間ができるだけ——ズームする
// ほど間隔そのものを細かくする。段に分ける理由と下限はdocs/modules/frontend/dynamic-weather-layers.md「共通契約」1。
// 境界は記号の拡大と同じ刻み。
const WIND_GRID_DETAIL_SPACING_STOPS: readonly { zoom: number; spacingDeg: number }[] = [
  { zoom: WIND_DETAIL_MIN_ZOOM, spacingDeg: 0.02 },
  { zoom: 13, spacingDeg: 0.01 },
  { zoom: 16, spacingDeg: 0.005 },
  { zoom: 19, spacingDeg: 0.0025 },
];

/** そのズームで詳細格子を求める間隔（度）。 */
export function windGridDetailSpacingDegForZoom(zoom: number): number {
  let spacingDeg = WIND_GRID_DETAIL_SPACING_STOPS[0].spacingDeg;
  for (const stop of WIND_GRID_DETAIL_SPACING_STOPS) {
    if (zoom >= stop.zoom) spacingDeg = stop.spacingDeg;
  }
  return spacingDeg;
}

// 1回に求める範囲の1辺を、間隔の何個分にするか（backendの点数の上限に余裕を持たせる。`min`で挟むので、上限が
// 下がっても自動で従う）。
const WIND_DETAIL_MAX_BBOX_SPAN_SIDE_INTERVALS = Math.min(
  25,
  Math.floor(Math.sqrt(windGridConfig.detail_max_points)) - 1,
);

/** 詳細格子へ渡す範囲。表示範囲が広ければ中心から、間隔に比例した最大の幅へ切り詰める。 */
export function clampWindDetailBbox(viewport: MapViewport, spacingDeg: number): Bbox {
  const halfSpan = (spacingDeg * WIND_DETAIL_MAX_BBOX_SPAN_SIDE_INTERVALS) / 2;
  const centerLon = (viewport.west + viewport.east) / 2;
  const centerLat = (viewport.south + viewport.north) / 2;
  return {
    minLon: Math.max(viewport.west, centerLon - halfSpan),
    minLat: Math.max(viewport.south, centerLat - halfSpan),
    maxLon: Math.min(viewport.east, centerLon + halfSpan),
    maxLat: Math.min(viewport.north, centerLat + halfSpan),
  };
}
