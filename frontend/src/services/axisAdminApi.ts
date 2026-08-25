import type { AxisDefinitionPayload, AxisDefinitionResponse } from "@/types/route";
import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";

// 評価軸定義のCRUD管理API（改善計画T270、backend/app/api/routers/axis_admin.py）の
// クライアント。改善計画T305: 以前はbackend（別オリジン）へ直接叩き、ブラウザが
// proxy.ts分のBasic認証情報を自動転送しないためAxisStudio.tsx側に専用のユーザー名/
// パスワード入力欄を持っていたが、/adminページ自体が既にBasic認証済みという二重ログインの
// 分かりにくさが実機フィードバックとして挙がったため撤去した。代わりに同一オリジンの
// Next.js route handler（frontend/src/app/admin/api/axis-definitions/配下、
// lib/adminApiProxy.ts参照）を経由する。このパスはproxy.tsのmatcher(/admin/:path*)に
// 含まれるため、ブラウザが/adminページ読込時に一度入力したBasic認証情報を、ブラウザ自身の
// 認証キャッシュから同一オリジン・同一realmの後続リクエストへ自動付与する（ブラウザ標準の
// 挙動）。route handler側がサーバー環境変数からbackend宛のAuthorizationヘッダを組み立てて
// 転送するため、backend向けの資格情報がブラウザ側に一切露出しない。
//
// GET系のfetchJson（POSTのみ対象外、lib/fetchJson.tsのコメント参照）は使わず、CRUD全
// メソッドをここで自前実装する（routeApi.ts: postJsonと同型の通信エラーハンドリングを
// PUT/DELETEにも揃える必要があるため）。

const API_BASE_URL = "/admin/api/axis-definitions";

async function adminFetch<T>(path: string, method: "GET" | "POST" | "PUT" | "DELETE", body?: unknown): Promise<T> {
  const startedAt = performance.now();
  debugLog("api:axisAdmin", `${method} ${path}`, body ? { body } : undefined);

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
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
  return adminFetch<AxisDefinitionResponse[]>(API_BASE_URL, "GET");
}

export function createAxisDefinition(payload: AxisDefinitionPayload): Promise<AxisDefinitionResponse> {
  return adminFetch<AxisDefinitionResponse>(API_BASE_URL, "POST", payload);
}

export function updateAxisDefinition(
  axisId: string,
  payload: AxisDefinitionPayload,
): Promise<AxisDefinitionResponse> {
  return adminFetch<AxisDefinitionResponse>(`${API_BASE_URL}/${encodeURIComponent(axisId)}`, "PUT", payload);
}

export function deleteAxisDefinition(axisId: string): Promise<void> {
  return adminFetch<void>(`${API_BASE_URL}/${encodeURIComponent(axisId)}`, "DELETE");
}

// 改善計画T302: 公開済み軸を下書きへ戻す。他フィールドは変更しない専用アクション
// （通常のupdateAxisDefinitionは公開済み軸に対して409で拒否される、
// backend/app/services/axis_registry_service.py: AxisRegistryAdminService.unpublish参照）。
export function unpublishAxisDefinition(axisId: string): Promise<AxisDefinitionResponse> {
  return adminFetch<AxisDefinitionResponse>(`${API_BASE_URL}/${encodeURIComponent(axisId)}/unpublish`, "POST");
}
