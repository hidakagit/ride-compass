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
import type { Bbox } from "@/components/Map/windLayer";
import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { debugLog } from "@/lib/debugLog";
import { fetchJson } from "@/lib/fetchJson";

export async function getCurrentWeather(point: Coordinates): Promise<WeatherConditions> {
  const params = new URLSearchParams({
    latitude: String(point.latitude),
    longitude: String(point.longitude),
  });
  const url = `${API_BASE_URL}/api/weather?${params}`;
  const data = await fetchJson<WeatherConditions>(url, { timeoutMs: 15000, category: "api:weather", errorLabel: "天候情報" });
  debugLog("api:weather", "詳細", { precipitation_probability_percent: data.precipitation_probability_percent });
  return data;
}

// 最寄りアメダス観測所の実測値（改善計画T387フォローアップ）。常設ヘッダー（WeatherPanel）が
// getCurrentWeather（Open-Meteo、TodayOutlook専用）とは独立に呼ぶ。取得失敗時はbackendが
// 502を返す契約（backend/app/api/routers/weather.py: get_amedas参照）。
export async function getAmedasObservation(point: Coordinates): Promise<AmedasObservation> {
  const params = new URLSearchParams({
    latitude: String(point.latitude),
    longitude: String(point.longitude),
  });
  const url = `${API_BASE_URL}/api/weather/amedas?${params}`;
  return fetchJson<AmedasObservation>(url, { timeoutMs: 15000, category: "api:amedas", errorLabel: "アメダス観測値" });
}

// 警報・注意報バッジ（改善計画T205）。取得失敗時もbackend側が空のwarningsで200を返す
// 契約（backend/app/api/routers/weather.py: get_weather_warnings参照）のため、
// ここでのエラーはネットワーク到達不能・タイムアウト等の通信エラーのみを表す。
export async function getWeatherWarnings(point: Coordinates): Promise<WeatherWarnings> {
  const params = new URLSearchParams({
    latitude: String(point.latitude),
    longitude: String(point.longitude),
  });
  const url = `${API_BASE_URL}/api/weather/warnings?${params}`;
  return fetchJson<WeatherWarnings>(url, {
    timeoutMs: 15000,
    category: "api:weatherWarnings",
    errorLabel: "警報・注意報",
  });
}

// WBGT警告バッジ（改善計画T174）。提供期間外（11〜3月）・取得失敗・「ほぼ安全」のいずれも
// backend側がlevel=nullで200を返す契約（backend/app/api/routers/weather.py: get_wbgt参照）
// のため、ここでのエラーはネットワーク到達不能・タイムアウト等の通信エラーのみを表す。
export async function getWbgtStatus(point: Coordinates): Promise<WbgtStatus> {
  const params = new URLSearchParams({
    latitude: String(point.latitude),
    longitude: String(point.longitude),
  });
  const url = `${API_BASE_URL}/api/weather/wbgt?${params}`;
  return fetchJson<WbgtStatus>(url, { timeoutMs: 15000, category: "api:wbgt", errorLabel: "暑さ指数" });
}

// 河川氾濫予報バッジ（改善計画T212）。地点解決失敗・取得失敗のいずれもbackend側が
// forecasts=[]で200を返す契約（backend/app/api/routers/weather.py: get_flood_forecast参照）
// のため、ここでのエラーはネットワーク到達不能・タイムアウト等の通信エラーのみを表す。
export async function getFloodForecasts(point: Coordinates): Promise<FloodForecasts> {
  const params = new URLSearchParams({
    latitude: String(point.latitude),
    longitude: String(point.longitude),
  });
  const url = `${API_BASE_URL}/api/weather/flood-forecast?${params}`;
  return fetchJson<FloodForecasts>(url, {
    timeoutMs: 15000,
    category: "api:floodForecast",
    errorLabel: "河川氾濫予報",
  });
}

// バックエンドの応答（times配列を1本だけ持つ、改善計画T203）を、フロント内部で使う
// 「各点がtimesを持つ」表現（WindGridPoint、windLayer.ts/useWeatherGrid.ts等の既存ロジックが
// 前提にしている形）へ戻す。ネットワーク転送量の削減（times重複の除去）だけを目的とした
// 変更であり、フロント内部のデータ構造・trim/mergeロジックには影響させない。
function toWindGridPoints(response: WindGridResponse): WindGridPoint[] {
  return response.points.map((point) => ({ ...point, times: response.times }));
}

// 風の格子点マップ（改善計画T178フォローアップ）。関東本土全域の固定格子点ぶんの
// 時間別風向・風速をまとめて取得する。取得失敗地点は既にバックエンド側で除外済み
// （backend/app/api/routers/weather.py: get_wind_grid参照）。
export async function getWindGrid(): Promise<WindGridPoint[]> {
  const url = `${API_BASE_URL}/api/weather/wind-grid`;
  const data = await fetchJson<WindGridResponse>(url, { timeoutMs: 15000, category: "api:windGrid", errorLabel: "風データ" });
  const points = toWindGridPoints(data);
  debugLog("api:windGrid", "詳細", { points: points.length });
  return points;
}

// 風の詳細格子（改善計画T180、ヒートマップ等の面表現用。T185でspacingDegをズーム依存に
// して間隔可変化）。表示範囲（bbox）に交差する密格子点ぶんの時間別風向・風速を取得する。
// bboxはwindLayer.tsのclampWindDetailBboxで安全な広さへクリップ済みのものを、spacingDegは
// windGridDetailSpacingDegForZoomで求めたものを渡す想定（呼び出し元が責務を持つ、この関数は
// 素直にリクエストするだけ）。
export async function getWindGridDetail(bbox: Bbox, spacingDeg: number): Promise<WindGridPoint[]> {
  const params = new URLSearchParams({
    min_lon: String(bbox.minLon),
    min_lat: String(bbox.minLat),
    max_lon: String(bbox.maxLon),
    max_lat: String(bbox.maxLat),
    spacing_deg: String(spacingDeg),
  });
  const url = `${API_BASE_URL}/api/weather/wind-grid-detail?${params}`;
  const data = await fetchJson<WindGridResponse>(url, {
    timeoutMs: 15000,
    category: "api:windGridDetail",
    errorLabel: "風データ(詳細)",
  });
  const points = toWindGridPoints(data);
  debugLog("api:windGridDetail", "詳細", { points: points.length });
  return points;
}
