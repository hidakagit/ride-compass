import { queryOptions } from "@tanstack/react-query";
import { fetchJson } from "@/lib/apiClient";
import { STATUS_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

/** `app/api/version/route.ts`の応答。 */
export interface FrontendVersion {
  commit: string | null;
  started_at: string;
}

// フロント自身が動いている版。メニューのバージョン表示と管理画面のシステム状況が読む。
function getFrontendVersion() {
  return fetchJson<FrontendVersion>("/api/version", {
    timeoutMs: STATUS_API_TIMEOUT_MS,
    category: "api:version",
    errorLabel: "フロントエンドのバージョン",
  });
}

/** 読む画面どうしで取得を1つに共有する問い合わせ。 */
export const frontendVersionQuery = queryOptions({ queryKey: ["frontend-version"], queryFn: getFrontendVersion });
