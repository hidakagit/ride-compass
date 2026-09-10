import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { STATUS_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

export async function checkBackendHealth(): Promise<boolean> {
  try {
    // タイムアウトが無いとバックエンドがハングした場合に「確認中...」が無期限に続く。
    const response = await fetch(`${API_BASE_URL}/health`, {
      signal: AbortSignal.timeout(STATUS_API_TIMEOUT_MS),
    });
    if (!response.ok) return false;
    const data = await response.json();
    return data.status === "ok";
  } catch {
    return false;
  }
}
