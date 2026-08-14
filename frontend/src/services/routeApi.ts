import type {
  RouteCandidate,
  RouteGenerateRequest,
  RouteGenerateResponse,
  RoutePreviewRequest,
  RouteSegment,
} from "@/types/route";
import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function postJson<T>(path: string, body: unknown, timeoutMs: number): Promise<T> {
  const startedAt = performance.now();
  debugLog("api:route", `POST ${path}`, { body });

  // タイムアウトが無いとバックエンドがハングした場合に「生成中...」が無期限に続く。
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  const durationMs = Math.round(performance.now() - startedAt);
  // バックエンドが全リクエストに付与するリクエストID(backend/app/infrastructure/request_log.py)。
  // サーバーログと突き合わせるためDebugConsoleと失敗時のエラーメッセージに含める。
  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog("api:route", `失敗 (HTTP ${response.status})`, { path, durationMs, requestId, errorBody });
    const detail = formatErrorDetail(errorBody?.detail) ?? `リクエストに失敗しました（HTTP ${response.status}）`;
    throw new Error(requestId ? `${detail}（req: ${requestId}）` : detail);
  }

  let data: T;
  try {
    data = await response.json();
  } catch {
    debugLog("api:route", "失敗 (不正なレスポンス)", { path, durationMs, requestId });
    throw new Error("サーバーからの応答の解析に失敗しました");
  }
  debugLog("api:route", "成功", { path, durationMs, requestId });
  return data;
}

export async function previewRoute(request: RoutePreviewRequest): Promise<RouteSegment> {
  return postJson<RouteSegment>("/api/routes/preview", request, 15000);
}

export async function generateRoutes(request: RouteGenerateRequest): Promise<RouteCandidate[]> {
  // road_graphエンジンはコールド時40〜70秒かかりうる(docs/architecture.md)ため、
  // previewより長めのタイムアウトにする。
  const result = await postJson<RouteGenerateResponse>("/api/routes/generate", request, 90000);
  debugLog("api:route", `ルーティングエンジン: ${result.engine}`, { count: result.routes.length });
  return result.routes;
}
