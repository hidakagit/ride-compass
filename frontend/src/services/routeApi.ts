import type {
  RouteCandidate,
  RouteGenerateRequest,
  RouteGenerateResponse,
  RoutePreviewRequest,
  RouteSegment,
} from "@/types/route";
import { debugLog } from "@/lib/debugLog";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const startedAt = performance.now();
  debugLog("api:route", `POST ${path}`, { body });

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const durationMs = Math.round(performance.now() - startedAt);
  // バックエンドが全リクエストに付与するリクエストID(backend/app/infrastructure/request_log.py)。
  // サーバーログと突き合わせるためDebugConsoleと失敗時のエラーメッセージに含める。
  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog("api:route", `失敗 (HTTP ${response.status})`, { path, durationMs, requestId, errorBody });
    const detail = errorBody?.detail ?? `リクエストに失敗しました（HTTP ${response.status}）`;
    throw new Error(requestId ? `${detail}（req: ${requestId}）` : detail);
  }

  const data = await response.json();
  debugLog("api:route", "成功", { path, durationMs, requestId });
  return data;
}

export async function previewRoute(request: RoutePreviewRequest): Promise<RouteSegment> {
  return postJson<RouteSegment>("/api/routes/preview", request);
}

export async function generateRoutes(request: RouteGenerateRequest): Promise<RouteCandidate[]> {
  const result = await postJson<RouteGenerateResponse>("/api/routes/generate", request);
  debugLog("api:route", `ルーティングエンジン: ${result.engine}`, { count: result.routes.length });
  return result.routes;
}
