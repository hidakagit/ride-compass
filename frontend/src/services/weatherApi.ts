import type { Coordinates } from "@/types/route";
import type { WeatherConditions, WindGridPoint } from "@/types/weather";
import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function getCurrentWeather(point: Coordinates): Promise<WeatherConditions> {
  const params = new URLSearchParams({
    latitude: String(point.latitude),
    longitude: String(point.longitude),
  });
  const url = `${API_BASE_URL}/api/weather?${params}`;
  const startedAt = performance.now();
  debugLog("api:weather", "リクエスト開始", { url });

  // タイムアウトが無いとバックエンドがハングした場合に「天候取得中...」が無期限に続く。
  const response = await fetch(url, { signal: AbortSignal.timeout(15000) });
  const durationMs = Math.round(performance.now() - startedAt);
  // サーバーログとの突き合わせ用リクエストID(routeApi.tsと同じ扱い)。
  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog("api:weather", `失敗 (HTTP ${response.status})`, { durationMs, requestId, errorBody }, "error");
    const detail = formatErrorDetail(errorBody?.detail) ?? `天候の取得に失敗しました[HTTP ${response.status}]`;
    throw new Error(requestId ? `${detail}[req: ${requestId}]` : detail);
  }

  let data: WeatherConditions;
  try {
    data = await response.json();
  } catch {
    debugLog("api:weather", "失敗 (不正なレスポンス)", { durationMs, requestId }, "error");
    throw new Error("天候情報の解析に失敗しました");
  }
  debugLog("api:weather", "成功", { durationMs, requestId, precipitation_probability_percent: data.precipitation_probability_percent });
  return data;
}

// 風の格子点マップ（改善計画T178フォローアップ）。関東本土全域の固定格子点ぶんの
// 時間別風向・風速をまとめて取得する。取得失敗地点は既にバックエンド側で除外済み
// （backend/app/api/routers/weather.py: get_wind_grid参照）。
export async function getWindGrid(): Promise<WindGridPoint[]> {
  const url = `${API_BASE_URL}/api/weather/wind-grid`;
  const startedAt = performance.now();
  debugLog("api:windGrid", "リクエスト開始", { url });

  const response = await fetch(url, { signal: AbortSignal.timeout(15000) });
  const durationMs = Math.round(performance.now() - startedAt);
  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog("api:windGrid", `失敗 (HTTP ${response.status})`, { durationMs, requestId, errorBody }, "error");
    const detail = formatErrorDetail(errorBody?.detail) ?? `風データの取得に失敗しました[HTTP ${response.status}]`;
    throw new Error(requestId ? `${detail}[req: ${requestId}]` : detail);
  }

  let data: WindGridPoint[];
  try {
    data = await response.json();
  } catch {
    debugLog("api:windGrid", "失敗 (不正なレスポンス)", { durationMs, requestId }, "error");
    throw new Error("風データの解析に失敗しました");
  }
  debugLog("api:windGrid", "成功", { durationMs, requestId, points: data.length });
  return data;
}
