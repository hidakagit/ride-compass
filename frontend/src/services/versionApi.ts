import { fetchJson } from "@/lib/apiClient";
import { STATUS_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

/** `app/api/version/route.ts`の応答。 */
export interface FrontendVersion {
  commit: string | null;
  started_at: string;
  /** 版に入っている直近の変更（新しい順。先頭は版のコミットそのもの）。取れなければ空。 */
  recent: { subject: string; committed_at: string }[];
}

// フロント自身が動いている版。メニューのバージョン表示と管理画面のシステム状況が読む。
export function getFrontendVersion() {
  return fetchJson<FrontendVersion>("/api/version", {
    timeoutMs: STATUS_API_TIMEOUT_MS,
    category: "api:version",
    errorLabel: "フロントエンドのバージョン",
  });
}
