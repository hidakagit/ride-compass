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

  // タイムアウトが無いとバックエンドがハングした場合に「天候取得中...」が無期限に続く。
  const response = await fetch(url, { signal: AbortSignal.timeout(15000) });
  const durationMs = Math.round(performance.now() - startedAt);
  // サーバーログとの突き合わせ用リクエストID(routeApi.tsと同じ扱い)。
  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog("api:weather", `失敗 (HTTP ${response.status})`, { durationMs, requestId, errorBody });
    const detail = errorBody?.detail ?? `天候の取得に失敗しました（HTTP ${response.status}）`;
    throw new Error(requestId ? `${detail}（req: ${requestId}）` : detail);
  }

  let data: WeatherConditions;
  try {
    data = await response.json();
  } catch {
    debugLog("api:weather", "失敗 (不正なレスポンス)", { durationMs, requestId });
    throw new Error("天候情報の解析に失敗しました");
  }
  debugLog("api:weather", "成功", { durationMs, requestId, precipitation_probability_percent: data.precipitation_probability_percent });
  return data;
}
