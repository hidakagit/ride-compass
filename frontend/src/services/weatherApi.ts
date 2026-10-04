import type { Coordinates } from "@/types/route";
import type { WindGridPoint, WindGridResponse } from "@/types/weather";
import { backendApi, getOptions, requestApi } from "@/lib/apiClient";
import { debugLog } from "@/lib/debugLog";
import { DEFAULT_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

function weatherOptions(category: string, errorLabel: string) {
  return getOptions({ timeoutMs: DEFAULT_API_TIMEOUT_MS, category, errorLabel });
}

/** 地点1つを問い合わせる項目。 */
function atPoint(point: Coordinates) {
  return { params: { query: { latitude: point.latitude, longitude: point.longitude } } };
}

export async function getCurrentWeather(point: Coordinates) {
  const data = await requestApi(
    (init) => backendApi.GET("/api/weather", { ...atPoint(point), ...init }),
    weatherOptions("api:weather", "天候情報"),
  );
  debugLog("api:weather", "詳細", { precipitation_mm: data.precipitation_mm });
  return data;
}

export const getAmedasObservation = (point: Coordinates) =>
  requestApi(
    (init) => backendApi.GET("/api/weather/amedas", { ...atPoint(point), ...init }),
    weatherOptions("api:amedas", "アメダス観測値"),
  );

// 警報・WBGT・河川氾濫の空の中身は「出ていない」を表す。backendが配信元から取れなかったときは502で投げる。
export const getWeatherWarnings = (point: Coordinates) =>
  requestApi(
    (init) => backendApi.GET("/api/weather/warnings", { ...atPoint(point), ...init }),
    weatherOptions("api:weatherWarnings", "警報・注意報"),
  );

export const getWbgtStatus = (point: Coordinates) =>
  requestApi(
    (init) => backendApi.GET("/api/weather/wbgt", { ...atPoint(point), ...init }),
    weatherOptions("api:wbgt", "暑さ指数"),
  );

export const getFloodForecasts = (point: Coordinates) =>
  requestApi(
    (init) => backendApi.GET("/api/weather/flood-forecast", { ...atPoint(point), ...init }),
    weatherOptions("api:floodForecast", "河川氾濫予報"),
  );

// 応答は時刻の列を1本だけ持つ（転送量を減らすため）。フロントの中では各点が時刻の列を持つ形で扱う。
function withTimes(data: WindGridResponse, category: string): WindGridPoint[] {
  const points = data.points.map((point) => ({ ...point, times: data.times }));
  debugLog(category, "詳細", { points: points.length });
  return points;
}

/** 風の格子点（対象範囲＝取り込んだ道路の範囲に敷いた固定の格子）。取れなかった点はbackendが除いてある。 */
export async function getWindGrid(): Promise<WindGridPoint[]> {
  const category = "api:windGrid";
  const data = await requestApi(
    (init) => backendApi.GET("/api/weather/wind-grid", init),
    weatherOptions(category, "風データ"),
  );
  return withTimes(data, category);
}

export interface Bbox {
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
}

/** 表示範囲の中の詳細な格子。範囲の広さと間隔は呼ぶ側が安全な値へ決めて渡す。 */
export async function getWindGridDetail(bbox: Bbox, spacingDeg: number): Promise<WindGridPoint[]> {
  const category = "api:windGridDetail";
  const query = {
    min_lon: bbox.minLon,
    min_lat: bbox.minLat,
    max_lon: bbox.maxLon,
    max_lat: bbox.maxLat,
    spacing_deg: spacingDeg,
  };
  const data = await requestApi(
    (init) => backendApi.GET("/api/weather/wind-grid-detail", { params: { query }, ...init }),
    weatherOptions(category, "風データ(詳細)"),
  );
  return withTimes(data, category);
}

/** JMAの動的タイルの在否。取れなくても呼ぶ側は間引きが効かないだけで表示は成り立つ。 */
export const fetchJmaTileIndex = () =>
  requestApi(
    (init) => backendApi.GET("/api/jma-tile-index", init),
    weatherOptions("api:jma-tile-index", "タイル在否インデックス"),
  );
