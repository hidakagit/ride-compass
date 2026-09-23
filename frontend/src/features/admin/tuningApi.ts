import type { components } from "@/types/generated/api";
import { requestJson } from "@/lib/fetchJson";
import { DEFAULT_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

// 較正値の管理API（backend/app/api/routers/tuning_admin.py）のクライアント。
// axisAdminApi.tsと同じく同一オリジンのNext.js route handler（app/admin/api/tuning/配下、
// lib/adminApiProxy.ts参照）を経由し、/adminページのブラウザ標準Basic認証セッションを
// そのまま再利用する。

const API_BASE_URL = "/admin/api/tuning";

/** 較正値1件の宣言と、いま効いている値。**項目はbackendが宣言から導く**ため、画面側に
 * 一覧を持たない（較正値を1つ足しても画面の変更は要らない）。 */
export type TuningParameter = components["schemas"]["TuningParameterView"];

function adminFetch<T>(path: string, method: "GET" | "PUT", body?: unknown): Promise<T> {
  return requestJson<T>(path, {
    method,
    body,
    timeoutMs: DEFAULT_API_TIMEOUT_MS,
    category: "api:tuning",
    messages: { failure: "リクエストに失敗しました", parseFailure: "サーバーからの応答の解析に失敗しました" },
    startLabel: `${method} ${path}`,
    ...(body !== undefined ? { requestMeta: { body } } : {}),
    logMeta: { path },
  });
}

export function listTuningParameters(): Promise<TuningParameter[]> {
  return adminFetch<TuningParameter[]>(API_BASE_URL, "GET");
}

/** 1件を書き換える。`value`にnullを渡すと既定へ戻す。 */
export function updateTuningParameter(paramId: string, value: number | null): Promise<TuningParameter> {
  return adminFetch<TuningParameter>(`${API_BASE_URL}/${encodeURIComponent(paramId)}`, "PUT", { value });
}
