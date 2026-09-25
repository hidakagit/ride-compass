import type { Coordinates } from "@/types/route";
import type {
  AmedasObservation,
  FloodForecasts,
  WbgtStatus,
  WeatherConditions,
  WeatherWarnings,
  WindGridPoint,
  WindGridResponse,
} from "@/types/weather";
import type { JmaTileIndexResponse } from "@/types/route";
import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { debugLog } from "@/lib/debugLog";
import { fetchJson } from "@/lib/fetchJson";
import { DEFAULT_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

function getAtPoint<T>(path: string, point: Coordinates, category: string, errorLabel: string): Promise<T> {
  const params = new URLSearchParams({ latitude: String(point.latitude), longitude: String(point.longitude) });
  return fetchJson<T>(`${API_BASE_URL}${path}?${params}`, { timeoutMs: DEFAULT_API_TIMEOUT_MS, category, errorLabel });
}

export async function getCurrentWeather(point: Coordinates): Promise<WeatherConditions> {
  const data = await getAtPoint<WeatherConditions>("/api/weather", point, "api:weather", "天候情報");
  debugLog("api:weather", "詳細", { precipitation_mm: data.precipitation_mm });
  return data;
}

export const getAmedasObservation = (point: Coordinates) =>
  getAtPoint<AmedasObservation>("/api/weather/amedas", point, "api:amedas", "アメダス観測値");

// 警報・WBGT・河川氾濫は、取得できなかったときもbackendが空の中身で200を返す。ここで投げるのは通信の失敗だけ。
export const getWeatherWarnings = (point: Coordinates) =>
  getAtPoint<WeatherWarnings>("/api/weather/warnings", point, "api:weatherWarnings", "警報・注意報");

export const getWbgtStatus = (point: Coordinates) =>
  getAtPoint<WbgtStatus>("/api/weather/wbgt", point, "api:wbgt", "暑さ指数");

export const getFloodForecasts = (point: Coordinates) =>
  getAtPoint<FloodForecasts>("/api/weather/flood-forecast", point, "api:floodForecast", "河川氾濫予報");

// 応答は時刻の列を1本だけ持つ（転送量を減らすため）。フロントの中では各点が時刻の列を持つ形で扱う。
async function getWindGridPoints(url: string, category: string, errorLabel: string): Promise<WindGridPoint[]> {
  const data = await fetchJson<WindGridResponse>(url, { timeoutMs: DEFAULT_API_TIMEOUT_MS, category, errorLabel });
  const points = data.points.map((point) => ({ ...point, times: data.times }));
  debugLog(category, "詳細", { points: points.length });
  return points;
}

/** 風の格子点（関東の固定の格子）。取れなかった点はbackendが除いてある。 */
export const getWindGrid = () => getWindGridPoints(`${API_BASE_URL}/api/weather/wind-grid`, "api:windGrid", "風データ");

export interface Bbox {
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
}

/** 表示範囲の中の詳細な格子。範囲の広さと間隔は呼ぶ側が安全な値へ決めて渡す。 */
export function getWindGridDetail(bbox: Bbox, spacingDeg: number): Promise<WindGridPoint[]> {
  const params = new URLSearchParams({
    min_lon: String(bbox.minLon),
    min_lat: String(bbox.minLat),
    max_lon: String(bbox.maxLon),
    max_lat: String(bbox.maxLat),
    spacing_deg: String(spacingDeg),
  });
  return getWindGridPoints(
    `${API_BASE_URL}/api/weather/wind-grid-detail?${params}`,
    "api:windGridDetail",
    "風データ(詳細)",
  );
}

/** JMAの動的タイルの在否。取れなくても呼ぶ側は間引きが効かないだけで表示は成り立つ。 */
export function fetchJmaTileIndex(): Promise<JmaTileIndexResponse> {
  return fetchJson<JmaTileIndexResponse>(`${API_BASE_URL}/api/jma-tile-index`, {
    timeoutMs: DEFAULT_API_TIMEOUT_MS,
    category: "api:jma-tile-index",
    errorLabel: "タイル在否インデックス",
  });
}
