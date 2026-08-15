import { debugLog } from "@/lib/debugLog";

// frontend/src/app/api/version/route.ts のレスポンス形状。フロントエンド（Next.jsサーバー）
// 自身のバージョン確認用のため、バックエンドAPI（NEXT_PUBLIC_API_URL）ではなく常に相対パス
// で同一オリジンへ問い合わせる。
export interface FrontendVersion {
  commit: string | null;
  started_at: string;
}

export async function getFrontendVersion(): Promise<FrontendVersion> {
  const startedAt = performance.now();
  debugLog("api:version", "リクエスト開始");
  const response = await fetch("/api/version", { signal: AbortSignal.timeout(5000) });
  const durationMs = Math.round(performance.now() - startedAt);

  if (!response.ok) {
    debugLog("api:version", `失敗 (HTTP ${response.status})`, { durationMs }, "error");
    throw new Error(`フロントエンドのバージョン取得に失敗しました（HTTP ${response.status}）`);
  }

  let data: FrontendVersion;
  try {
    data = await response.json();
  } catch {
    debugLog("api:version", "失敗 (不正なレスポンス)", { durationMs }, "error");
    throw new Error("フロントエンドのバージョンの解析に失敗しました");
  }
  debugLog("api:version", "成功", { durationMs });
  return data;
}
