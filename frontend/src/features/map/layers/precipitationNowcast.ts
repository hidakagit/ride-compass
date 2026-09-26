// 降水の色の段・凡例と、自前の格子から描く降水の塗り（gridFill）。
//
// 「降水」チップの時系列は、気象庁ナウキャスト（実況の外挿、60分先まで）→気象庁 降水短時間予報
// （数値予報モデル、15時間先まで）→風と共有の格子点マップが相乗りで返す降水量（気象庁MSM、1〜3日先）
// の3段を1本につないだもの（精度が高い方から）。段の並び・時刻一覧の読み方は源泉の宣言が持ち、
// つなぎ方は`weatherSources.ts`が持つ。ここは格子の段の描き方だけを持つ。

import weatherScales from "@/types/generated/weather-scales.json";
import { buildRangeLegendBands, type MapColorLegendBand } from "@/lib/mapDisplay/mapColorLegend";
import {
  gridCellRing,
  gridToFeatureCollection,
  type DynamicWeatherRenderPayload,
} from "@/features/map/layers/dynamicWeather";
import type { WindGridPoint } from "@/types/weather";

// 降水強度→色の段（帯の下限）と段の呼び名。値・色・呼び名は源泉（backend
// `domain/weather_display.py`）が持ち、格子の塗り（`features/map/scene/groups/weather.ts`）と
// 地図チップの凡例の両方がこの並びを使う。気象庁はタイル配色のカラーコードを公開していないため、
// 色はナウキャスト等のタイル画像の色と厳密には一致しない（凡例としての目安）。
export const PRECIPITATION_COLOR_STOPS: readonly { mmPerHour: number; color: string; name: string }[] =
  weatherScales.precipitation.map((stop) => ({ mmPerHour: stop.value, color: stop.color, name: stop.name }));

// 格子の塗り（gridFill）でこの値未満は「降っていない」として塗らない。境はbackendの宣言が持ち、
// 天気コードの雨の判定・「今日の見通し」の予想降水量の「-」と同じ値。
export const PRECIPITATION_NONE_THRESHOLD_MM = weatherScales.precipitation_none_below_mm;

/** 降水強度の凡例（地図チップ）。色の段1つにつき1行。 */
export const PRECIPITATION_INTENSITY_LEVELS: readonly MapColorLegendBand[] = buildRangeLegendBands(
  PRECIPITATION_COLOR_STOPS.slice(1).map((stop) => stop.mmPerHour),
  PRECIPITATION_COLOR_STOPS.map((stop) => stop.color),
  "mm/h",
  PRECIPITATION_COLOR_STOPS.map((stop) => stop.name),
);

/** 格子の`index`番目の時刻の降水量を、各格子点を中心とする1辺`spacingDeg`の正方形で塗る。
 * 値が欠けた格子点は飛ばす（1点の欠損で全体を落とさない）。「ほぼ降水なし」の間引き
 * （PRECIPITATION_NONE_THRESHOLD_MM）はここでは行わない（MapLibre側のfilterに任せる）。
 * `spacingDeg`は描く格子の実際の間隔（ズーム依存の詳細格子になりうる。`useWeatherGrid.ts`）。 */
export function precipitationCells(
  grid: readonly WindGridPoint[],
  index: number,
  spacingDeg: number,
): DynamicWeatherRenderPayload {
  return {
    kind: "gridFill",
    geojson: gridToFeatureCollection(
      grid,
      (point) => point.precipitation_mm[index] ?? null,
      (point, mmPerHour) => ({
        type: "Feature",
        geometry: { type: "Polygon", coordinates: [gridCellRing(point.latitude, point.longitude, spacingDeg)] },
        properties: { mmPerHour },
      }),
    ),
  };
}
