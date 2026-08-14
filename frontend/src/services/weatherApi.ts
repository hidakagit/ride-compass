import type { Coordinates } from "@/types/route";
import type { WeatherConditions } from "@/types/weather";
import { debugLog } from "@/lib/debugLog";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function getCurrentWeather(point: Coordinates): Promise<WeatherConditions> {
  const params = new URLSearchParams({
    latitude: String(point.latitude),
    longitude: String(point.longitude),
  });
  const url = `${API_BASE_URL}/api/weather?${params}`;
  const startedAt = performance.now();
  debugLog("api:weather", "リクエスト開始", { url });

  const response = await fetch(url);
  const durationMs = Math.round(performance.now() - startedAt);

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog("api:weather", `失敗 (HTTP ${response.status})`, { durationMs, errorBody });
    throw new Error(errorBody?.detail ?? `天候の取得に失敗しました（HTTP ${response.status}）`);
  }

  const data = await response.json();
  debugLog("api:weather", "成功", { durationMs, precipitation_probability_percent: data.precipitation_probability_percent });
  return data;
}
