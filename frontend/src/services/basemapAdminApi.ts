import { DEFAULT_API_TIMEOUT_MS } from "@/lib/apiTimeouts";
import { requestJson } from "@/lib/fetchJson";

// サーバー側タイルファイルキャッシュの全消去（backend POST /api/admin/basemap/refresh、
// Basic認証必須）のクライアント。derivedDataFreshnessApi.tsと同じ理由で同一オリジンの
// Next.js route handler（app/admin/api/basemap-refresh/、lib/adminApiProxy.ts参照）を経由し、
// /adminページのブラウザ標準Basic認証セッションをそのまま再利用する。

const API_PATH = "/admin/api/basemap-refresh";

export async function refreshTileCache(): Promise<void> {
  await requestJson<{ status: string }>(API_PATH, {
    method: "POST",
    timeoutMs: DEFAULT_API_TIMEOUT_MS,
    category: "api:basemap-refresh",
    messages: {
      failure: "タイルキャッシュの消去に失敗しました",
      parseFailure: "タイルキャッシュの消去結果の解析に失敗しました",
    },
  });
}
