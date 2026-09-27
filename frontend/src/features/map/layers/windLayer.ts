// 風と降水が共有する格子の扱い（取り損ねた地点を補う・描く格子を時刻で選ぶ・詳細格子の間隔と範囲）と、風の矢印。

import palette from "@/types/generated/palette.json";
import type { Bbox } from "@/services/weatherApi";
import weatherScales from "@/types/generated/weather-scales.json";
import { gridToFeatureCollection, type DynamicWeatherRenderPayload } from "@/features/map/layers/dynamicWeather";
import type { WindGridPoint } from "@/types/weather";
import windGridConfig from "@/types/generated/wind-grid-config.json";
import { buildRangeLegendBands, type MapColorLegendBand } from "@/lib/mapDisplay/mapColorLegend";

/** 格子の点と、その格子の間隔（度）。 */
export interface SpacedWindGrid {
  spacingDeg: number;
  points: readonly WindGridPoint[];
}

/** 格子点の値の列のうち、時刻`time`（格子の時刻の値そのもの）の位置。その時刻を持たない点は-1。値は位置ではなく
 * 時刻で引く——backendは取った時点の正時から先を返すので、取った時刻が違う格子（粗い格子と詳細格子、前回の値で
 * 補った点）は同じ位置が別の時刻を指す。 */
export function timeIndexOf(point: WindGridPoint, time: string): number {
  return point.times.indexOf(time);
}

/** 時刻`time`に描く格子。詳細格子がその時刻を持てば詳細格子で粗い格子を置き換え（半透明の面を2枚重ねると、
 * 重なった所だけ濃く見える）、持たなければ粗い格子（詳細格子は取った時刻の分だけ予報の先の端が手前で終わる）。 */
export function gridAtTime(
  coarse: readonly WindGridPoint[],
  detail: SpacedWindGrid | null,
  time: string,
): SpacedWindGrid {
  if (detail !== null && detail.points.length > 0 && timeIndexOf(detail.points[0], time) >= 0) return detail;
  return { spacingDeg: WIND_GRID_SPACING_DEG, points: coarse };
}

/** 新しい格子に、前回の格子のうち新しい方に無い地点を補う。backendは取れなかった地点を応答から除くので、取り直す
 * たびに欠ける地点が変わる——古い値が残る方が、地図に穴が開くよりよい。地点は緯度経度で見分ける。補った点は前回の
 * 時刻の列を持ったまま残る（描くときに時刻で引く）。 */
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

/** 時刻`time`の風を、格子点ごとの矢印（gridMark）にする。値の欠けた点・その時刻を持たない点は飛ばす。 */
export function windArrows(grid: readonly WindGridPoint[], time: string): DynamicWeatherRenderPayload {
  const geojson: GeoJSON.FeatureCollection<GeoJSON.Point, WindPointFeatureProperties> = gridToFeatureCollection(
    grid,
    (point) => {
      const index = timeIndexOf(point, time);
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
