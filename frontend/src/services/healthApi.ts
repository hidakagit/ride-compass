import { API_BASE_URL } from "@/lib/apiBaseUrl";

export async function checkBackendHealth(): Promise<boolean> {
  try {
    // タイムアウトが無いとバックエンドがハングした場合に「確認中...」が無期限に続く。
    const response = await fetch(`${API_BASE_URL}/health`, { signal: AbortSignal.timeout(5000) });
    if (!response.ok) return false;
    const data = await response.json();
    return data.status === "ok";
  } catch {
    return false;
  }
}
