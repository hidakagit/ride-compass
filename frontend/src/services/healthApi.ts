import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { STATUS_API_TIMEOUT_MS } from "@/lib/apiTimeouts";
import { requestJson } from "@/lib/fetchJson";

interface HealthResponse {
  status?: string;
}

/** backendへ疎通できるか。**失敗の種類を呼び出し側へ返さない**（画面は「OK/接続できません」の
 * 2値しか出さない）が、失敗の中身はfetchJsonの骨格がdebugLogへ残す——素のfetchと`catch {}`で
 * 書くと、タイムアウトなのか5xxなのかが記録にも残らない。 */
export async function checkBackendHealth(): Promise<boolean> {
  try {
    const data = await requestJson<HealthResponse>(`${API_BASE_URL}/health`, {
      timeoutMs: STATUS_API_TIMEOUT_MS,
      category: "api:health",
      messages: {
        failure: "バックエンドへの疎通確認に失敗しました",
        parseFailure: "バックエンドへの疎通確認に失敗しました",
      },
    });
    return data?.status === "ok";
  } catch {
    return false;
  }
}
