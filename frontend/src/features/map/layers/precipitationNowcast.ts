// 降水の色の段・凡例と、自前の格子から描く降水の塗り（gridFill）。

import weatherScales from "@/types/generated/weather-scales.json";
import { buildRangeLegendBands, type MapColorLegendBand } from "@/lib/mapDisplay/mapColorLegend";
import {
  gridCellRing,
  gridToFeatureCollection,
  type DynamicWeatherRenderPayload,
} from "@/features/map/layers/dynamicWeather";
import { timeIndexOf } from "@/features/map/layers/windLayer";
import type { WindGridPoint } from "@/types/weather";

// 降水強度→色の段（帯の下限）と段の呼び名。値・色・呼び名は源泉（backend
// `domain/weather_display.py`）が持つ。気象庁の降水のタイルも中継がこの段の色へ塗り替えて配るため、
// 時系列のどの段の地図の色も凡例の行と一致する。
export const PRECIPITATION_COLOR_STOPS: readonly { mmPerHour: number; color: string; name: string }[] =
  weatherScales.precipitation.map((stop) => ({ mmPerHour: stop.value, color: stop.color, name: stop.name }));

// 格子の塗り（gridFill）でこの値未満は「降っていない」として塗らない。境はbackendの宣言が持つ。
export const PRECIPITATION_NONE_THRESHOLD_MM = weatherScales.precipitation_none_below_mm;

/** 降水強度の凡例（地図チップ）。色の段1つにつき1行。 */
export const PRECIPITATION_INTENSITY_LEVELS: readonly MapColorLegendBand[] = buildRangeLegendBands(
  PRECIPITATION_COLOR_STOPS.slice(1).map((stop) => stop.mmPerHour),
  PRECIPITATION_COLOR_STOPS.map((stop) => stop.color),
  "mm/h",
  PRECIPITATION_COLOR_STOPS.map((stop) => stop.name),
);

/** 時刻`time`の降水量を、各格子点を中心とする1辺`spacingDeg`の正方形で塗る。
 * 値が欠けた格子点・その時刻を持たない格子点は飛ばす（1点の欠損で全体を落とさない）。「ほぼ降水なし」の間引き
 * （PRECIPITATION_NONE_THRESHOLD_MM）はここでは行わない（MapLibre側のfilterに任せる）。
 * `spacingDeg`は描く格子の実際の間隔（ズーム依存の詳細格子になりうる。`windLayer.ts: gridAtTime`）。 */
export function precipitationCells(
  grid: readonly WindGridPoint[],
  time: string,
  spacingDeg: number,
): DynamicWeatherRenderPayload {
  return {
    kind: "gridFill",
    geojson: gridToFeatureCollection(
      grid,
      (point) => point.precipitation_mm[timeIndexOf(point, time)] ?? null,
      (point, mmPerHour) => ({
        type: "Feature",
        geometry: { type: "Polygon", coordinates: [gridCellRing(point.latitude, point.longitude, spacingDeg)] },
        properties: { mmPerHour },
      }),
    ),
  };
}
