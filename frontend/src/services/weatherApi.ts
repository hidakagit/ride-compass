import type { Coordinates } from "@/types/route";
import type { WeatherConditions, WindGridPoint } from "@/types/weather";
import type { Bbox } from "@/components/Map/windLayer";
import { debugLog } from "@/lib/debugLog";
import { fetchJson } from "@/lib/fetchJson";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

// 風の格子点マップ（改善計画T178フォローアップ）。関東本土全域の固定格子点ぶんの
// 時間別風向・風速をまとめて取得する。取得失敗地点は既にバックエンド側で除外済み
// （backend/app/api/routers/weather.py: get_wind_grid参照）。
export async function getWindGrid(): Promise<WindGridPoint[]> {
  const url = `${API_BASE_URL}/api/weather/wind-grid`;
  const data = await fetchJson<WindGridPoint[]>(url, { timeoutMs: 15000, category: "api:windGrid", errorLabel: "風データ" });
  debugLog("api:windGrid", "詳細", { points: data.length });
  return data;
}

// 風の詳細格子（改善計画T180、ヒートマップ等の面表現用）。表示範囲（bbox）に交差する
// 密格子点ぶんの時間別風向・風速を取得する。bboxはwindLayer.tsのclampWindDetailBboxで
// 安全な広さへクリップ済みのものを渡す想定（呼び出し元がクリップ責務を持つ、この関数は
// 素直にリクエストするだけ）。
export async function getWindGridDetail(bbox: Bbox): Promise<WindGridPoint[]> {
  const params = new URLSearchParams({
    min_lon: String(bbox.minLon),
    min_lat: String(bbox.minLat),
    max_lon: String(bbox.maxLon),
    max_lat: String(bbox.maxLat),
  });
  const url = `${API_BASE_URL}/api/weather/wind-grid-detail?${params}`;
  const data = await fetchJson<WindGridPoint[]>(url, {
    timeoutMs: 15000,
    category: "api:windGridDetail",
    errorLabel: "風データ(詳細)",
  });
  debugLog("api:windGridDetail", "詳細", { points: data.length });
  return data;
}
