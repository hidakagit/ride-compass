import type { AxisDefinitionPayload, AxisDefinitionResponse } from "@/types/route";
import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";
import { adminBasicAuthHeader } from "@/lib/adminToken";

// 評価軸定義のCRUD管理API（改善計画T270、backend/app/api/routers/axis_admin.py）の
// クライアント。Authorization: Basicヘッダはlib/adminToken.tsに保存された資格情報から
// 組み立てる（改善計画T272、Basic認証化。誤った資格情報はbackend側の
// require_admin_basic_authが401で拒否する）。GET系のfetchJson（POSTのみ対象外、
// lib/fetchJson.tsのコメント参照）は使わず、CRUD全メソッドをここで自前実装する
// （routeApi.ts: postJsonと同型の通信エラーハンドリングをPUT/DELETEにも揃える必要が
// あるため）。

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function adminFetch<T>(path: string, method: "GET" | "POST" | "PUT" | "DELETE", body?: unknown): Promise<T> {
  const startedAt = performance.now();
  debugLog("api:axisAdmin", `${method} ${path}`, body ? { body } : undefined);

  const authHeader = adminBasicAuthHeader();
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(authHeader !== null ? { Authorization: authHeader } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(15000),
    });
  } catch (error) {
    debugLog(
      "api:axisAdmin",
      "失敗 (通信エラー)",
      { path, error: error instanceof Error ? `${error.name}: ${error.message}` : String(error) },
      "error",
    );
    throw error instanceof Error ? error : new Error(`リクエストに失敗しました: ${String(error)}`);
  }
  const durationMs = Math.round(performance.now() - startedAt);
  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog("api:axisAdmin", `失敗 (HTTP ${response.status})`, { path, durationMs, requestId, errorBody }, "error");
    const detail = formatErrorDetail(errorBody?.detail) ?? `リクエストに失敗しました[HTTP ${response.status}]`;
    throw new Error(requestId ? `${detail}[req: ${requestId}]` : detail);
  }

  if (response.status === 204) {
    debugLog("api:axisAdmin", "成功", { path, durationMs, requestId });
    return undefined as T;
  }

  let data: T;
  try {
    data = await response.json();
  } catch {
    debugLog("api:axisAdmin", "失敗 (不正なレスポンス)", { path, durationMs, requestId }, "error");
    throw new Error("サーバーからの応答の解析に失敗しました");
  }
  debugLog("api:axisAdmin", "成功", { path, durationMs, requestId });
  return data;
}

export function listAxisDefinitions(): Promise<AxisDefinitionResponse[]> {
  return adminFetch<AxisDefinitionResponse[]>("/api/admin/axis-definitions", "GET");
}

export function createAxisDefinition(payload: AxisDefinitionPayload): Promise<AxisDefinitionResponse> {
  return adminFetch<AxisDefinitionResponse>("/api/admin/axis-definitions", "POST", payload);
}

export function updateAxisDefinition(
  axisId: string,
  payload: AxisDefinitionPayload,
): Promise<AxisDefinitionResponse> {
  return adminFetch<AxisDefinitionResponse>(`/api/admin/axis-definitions/${encodeURIComponent(axisId)}`, "PUT", payload);
}

export function deleteAxisDefinition(axisId: string): Promise<void> {
  return adminFetch<void>(`/api/admin/axis-definitions/${encodeURIComponent(axisId)}`, "DELETE");
}

// 改善計画T302: 公開済み軸を下書きへ戻す。他フィールドは変更しない専用アクション
// （通常のupdateAxisDefinitionは公開済み軸に対して409で拒否される、
// backend/app/services/axis_registry_service.py: AxisRegistryAdminService.unpublish参照）。
export function unpublishAxisDefinition(axisId: string): Promise<AxisDefinitionResponse> {
  return adminFetch<AxisDefinitionResponse>(
    `/api/admin/axis-definitions/${encodeURIComponent(axisId)}/unpublish`,
    "POST",
  );
}
