import type {
  GenerationConditions,
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
    debugLog("api:route", `失敗 (HTTP ${response.status})`, { path, durationMs, requestId, errorBody }, "error");
    const detail = formatErrorDetail(errorBody?.detail) ?? `リクエストに失敗しました[HTTP ${response.status}]`;
    throw new Error(requestId ? `${detail}[req: ${requestId}]` : detail);
  }

  let data: T;
  try {
    data = await response.json();
  } catch {
    debugLog("api:route", "失敗 (不正なレスポンス)", { path, durationMs, requestId }, "error");
    throw new Error("サーバーからの応答の解析に失敗しました");
  }
  debugLog("api:route", "成功", { path, durationMs, requestId });
  return data;
}

export async function previewRoute(request: RoutePreviewRequest): Promise<RouteSegment> {
  return postJson<RouteSegment>("/api/routes/preview", request, 15000);
}

export interface GenerateRoutesResult {
  routes: RouteCandidate[];
  conditions: GenerationConditions;
  engine: string;
}

export async function generateRoutes(request: RouteGenerateRequest): Promise<GenerateRoutesResult> {
  // road_graphエンジンの冷パスは、バックエンドのDBコマンドタイムアウト
  // (ROUTE_GENERATION_COMMAND_TIMEOUT_SECONDS=180秒、backend/app/infrastructure/database.py)
  // より短いとフロントが先にタイムアウトしてしまう(改善計画T248で発覚)。本番実測の
  // 最悪ケース(王子30km、save_graphのバルクUPSERT込みでtotal_ms=315,859≒316秒)を
  // 安全マージン込みで上回る値にする。
  const result = await postJson<RouteGenerateResponse>("/api/routes/generate", request, 360000);
  debugLog("api:route", `ルーティングエンジン: ${result.engine}`, { count: result.routes.length });
  // conditionsは実験スロット（比較・再現用、研究インターフェース改善 §10-3/6）の入力になる。
  return { routes: result.routes, conditions: result.conditions, engine: result.engine };
}
