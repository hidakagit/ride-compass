import { fetchJson } from "@/lib/fetchJson";

// frontend/src/app/api/version/route.ts のレスポンス形状。フロントエンド（Next.jsサーバー）
// 自身のバージョン確認用のため、バックエンドAPI（NEXT_PUBLIC_API_URL）ではなく常に相対パス
// で同一オリジンへ問い合わせる。
export interface FrontendVersion {
  commit: string | null;
  started_at: string;
}

export async function getFrontendVersion(): Promise<FrontendVersion> {
  return fetchJson<FrontendVersion>("/api/version", {
    timeoutMs: 5000,
    category: "api:version",
    errorLabel: "フロントエンドのバージョン",
  });
}
