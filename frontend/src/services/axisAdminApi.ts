import type { AxisDefinitionPayload, AxisDefinitionResponse } from "@/types/route";
import { requestJson } from "@/lib/fetchJson";

// 評価軸定義のCRUD管理API（backend/app/api/routers/axis_admin.py）のクライアント。
// 同一オリジンのNext.js route handler（frontend/src/app/admin/api/axis-definitions/配下、
// lib/adminApiProxy.ts参照）を経由する。このパスはproxy.tsのmatcher(/admin/:path*)に
// 含まれるため、ブラウザが/adminページ読込時に一度入力したBasic認証情報を、ブラウザ自身の
// 認証キャッシュから同一オリジン・同一realmの後続リクエストへ自動付与する（ブラウザ標準の
// 挙動）。route handler側がサーバー環境変数からbackend宛のAuthorizationヘッダを組み立てて
// 転送するため、backend向けの資格情報がブラウザ側に一切露出しない。
//
// CRUD全メソッドが共通骨格（lib/fetchJson.ts: requestJson）を通る。DELETEの204は
// requestJson側がundefinedを返す。

const API_BASE_URL = "/admin/api/axis-definitions";

function adminFetch<T>(path: string, method: "GET" | "POST" | "PUT" | "DELETE", body?: unknown): Promise<T> {
  return requestJson<T>(path, {
    method,
    body,
    timeoutMs: 15000,
    category: "api:axisAdmin",
    messages: { failure: "リクエストに失敗しました", parseFailure: "サーバーからの応答の解析に失敗しました" },
    startLabel: `${method} ${path}`,
    ...(body !== undefined ? { requestMeta: { body } } : {}),
    logMeta: { path },
  });
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

// 公開済み軸を下書きへ戻す。他フィールドは変更しない専用アクション
// （通常のupdateAxisDefinitionは公開済み軸に対して409で拒否される、
// backend/app/services/axis_registry_service.py: AxisRegistryAdminService.unpublish参照）。
export function unpublishAxisDefinition(axisId: string): Promise<AxisDefinitionResponse> {
  return adminFetch<AxisDefinitionResponse>(`${API_BASE_URL}/${encodeURIComponent(axisId)}/unpublish`, "POST");
}
