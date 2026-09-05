import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";

// GET系APIクライアント（weatherApi.ts・debugStatsApi.ts・versionApi.ts）が共有する
// 「fetch→通信エラーのtry/catch→response.ok確認→エラーボディ解析→整形したErrorをthrow→
// 各段階でdebugLog記録」という共通パターンをここへ集約する。
//
// POST系（routeApi.ts: postJson・regionApi.ts: fetchBreakdown等）は対象外にしている。
// 「取得に失敗しました」という動詞がGET（取得）には自然に当てはまる一方、POSTは
// リクエストごとに動詞が変わる（生成・更新・送信等）ため、汎用テンプレートに無理に
// 押し込めるとかえって不自然な文言になる。POST系は既にpostJson/fetchBreakdownという
// ファイル内の共通ヘルパーへ集約済みで、GET系ほど重複コストが高くないため対象外とした。

export interface FetchJsonOptions {
  /** タイムアウト（ミリ秒）。バックエンドがハングした場合に「取得中...」が無期限に続くのを防ぐ。 */
  timeoutMs: number;
  /** DebugConsole上のカテゴリ（例: "api:weather"）。 */
  category: string;
  /** エラーメッセージの生成に使う対象名。「{errorLabel}の取得に失敗しました」
   * 「{errorLabel}の解析に失敗しました」の形で使われる。 */
  errorLabel: string;
  /** 「リクエスト開始」ログへ追加で載せたい情報（urlは自動で載るため指定不要）。 */
  requestMeta?: Record<string, unknown>;
}

/** GET専用のfetch共通ラッパー。成功時はレスポンスをJSONとしてパースして返し、失敗時は
 * 各段階（通信エラー・HTTPエラー・レスポンス解析エラー）をdebugLogへ記録した上で
 * 人間可読なメッセージのErrorをthrowする。 */
export async function fetchJson<T>(url: string, options: FetchJsonOptions): Promise<T> {
  const { timeoutMs, category, errorLabel, requestMeta } = options;
  const startedAt = performance.now();
  debugLog(category, "リクエスト開始", requestMeta ? { url, ...requestMeta } : { url });

  // fetch()自体の失敗（バックエンド到達不能等の通信エラー）はresponse.okのチェック以前の
  // 例外として送出されるため、ここで捕まえずにいると失敗がデバッグログに一切残らない
  // （T105調査で発覚、regionApi.tsのrefreshBasemapCacheで確立したパターン）。
  let response: Response;
  try {
    response = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
  } catch (error) {
    debugLog(
      category,
      "失敗 (通信エラー)",
      {
        durationMs: Math.round(performance.now() - startedAt),
        error: error instanceof Error ? error.message : String(error),
      },
      "error",
    );
    throw error instanceof Error ? error : new Error(`${errorLabel}の取得に失敗しました`);
  }
  const durationMs = Math.round(performance.now() - startedAt);
  // バックエンドが全リクエストに付与するリクエストID(backend/app/infrastructure/request_log.py)。
  // サーバーログとの突き合わせ用にエラーメッセージへ含める。
  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog(category, `失敗 (HTTP ${response.status})`, { durationMs, requestId, errorBody }, "error");
    const detail = formatErrorDetail(errorBody?.detail) ?? `${errorLabel}の取得に失敗しました[HTTP ${response.status}]`;
    throw new Error(requestId ? `${detail}[req: ${requestId}]` : detail);
  }

  let data: T;
  try {
    data = await response.json();
  } catch {
    debugLog(category, "失敗 (不正なレスポンス)", { durationMs, requestId }, "error");
    throw new Error(`${errorLabel}の解析に失敗しました`);
  }
  debugLog(category, "成功", { durationMs, requestId });
  return data;
}
