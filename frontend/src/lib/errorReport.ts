import { API_BASE_URL } from "@/lib/apiBaseUrl";
import type { paths } from "@/types/generated/api";

// 画面で起きたエラーをbackendへ報告する口（`POST /api/client-errors`。記録は定期の見張りが読んで知らせる）。
// 送るのは種類・粗い名前・画面のパスだけ——記録は認証なしで読めるので、例外の文・問い合わせ・座標を送らない。

type ClientErrorReport = NonNullable<paths["/api/client-errors"]["post"]["requestBody"]>["content"]["text/plain"];

/** 報告の種類。 */
export type ErrorReportKind = ClientErrorReport["kind"];

/** 1回の表示で送る上限。同じ不具合が描画のたびに起きても、報告で backend のレート制限を埋めない。 */
export const MAX_REPORTS_PER_PAGE = 10;

// backendの`ClientErrorReport`が受ける綴り。受けない綴り（日本語の分類・符号化したパス等）は伏せて送り、種類は残す。
const NAME_PATTERN = /^[A-Za-z0-9_.:-]{1,80}$/;
const PAGE_PATTERN = /^\/[A-Za-z0-9_.\/-]{0,199}$/;

const sent = new Set<string>();

/** 例外から報告の名前を取る（`TypeError`等の型の名前。`Error`でない値が投げられたら値の型）。 */
export function errorName(error: unknown): string {
  return error instanceof Error ? error.name : typeof error;
}

/**
 * 1件を送る。同じ種類・名前・画面は1回の表示で1度だけ送る。
 *
 * `navigator.sendBeacon`の`text/plain`はCORSの事前の問い合わせが起きない形なので、backendのCORSの設定が食い違って
 * 画面の通信が全部落ちているときも届く。応答は読まない（読めない）。
 */
export function reportError(kind: ErrorReportKind, name: string): void {
  if (typeof navigator === "undefined" || typeof navigator.sendBeacon !== "function") return;
  const { pathname } = window.location;
  const page = PAGE_PATTERN.test(pathname) ? pathname : "/";
  const key = `${kind} ${name} ${page}`;
  if (sent.has(key) || sent.size >= MAX_REPORTS_PER_PAGE) return;
  sent.add(key);
  const report: ClientErrorReport = { kind, name: NAME_PATTERN.test(name) ? name : "-", page };
  const body = JSON.stringify(report);
  navigator.sendBeacon(`${API_BASE_URL}/api/client-errors`, new Blob([body], { type: "text/plain" }));
}

/**
 * backendへの通信の失敗を報告する。端末が網から外れている・画面が裏に回っている間の失敗は、こちらの不具合ではない
 * （裏に回った画面の通信をブラウザが切る）ので送らない。
 */
export function reportNetworkFailure(kind: "network" | "timeout", category: string): void {
  if (typeof document === "undefined" || !navigator.onLine || document.visibilityState === "hidden") return;
  reportError(kind, category);
}
