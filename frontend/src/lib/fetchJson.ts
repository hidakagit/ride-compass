import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";

// backend APIクライアントが共有する「fetch→通信エラーのtry/catch→response.ok確認→
// エラーボディ解析→x-request-id付きのErrorをthrow→各段階でdebugLog記録」という
// 7段の骨格をここへ集約する。
//
// **メソッド・成功時のボディ解釈・エラー文言だけが呼び出しごとに違う**ため、その3点を
// 引数（`method`/`body`・`requestOk`か`requestJson`か・`messages`）で受け取り、それ以外は
// 分岐を持たない。骨格を各クライアントへ写経すると、片方だけ改良された非対称が
// 静かに生まれる（`cause`ログとタイムアウト判別がPOST系1箇所にしか無い状態が実際に
// 生まれていた）。
//
// 使い分け:
// - `requestJson`: 応答をJSONとして解釈して返す（204はundefined）。大半のクライアント。
// - `requestOk`: 成功時の`Response`をそのまま返す。成功ログのfieldsが呼び出しごとに
//   違う場合（本文からwayCount等を数える等）に使う。成功ログは呼び出し側が出す。
// - `fetchJson`: `requestJson`のGET向けの薄い糖衣。エラー文言を`errorLabel`から
//   「◯◯の取得に失敗しました」「◯◯の解析に失敗しました」で組み立てる。

/** エラー時に利用者へ見せる文言。detailがサーバーから返る場合はそちらを優先する。 */
export interface ApiRequestMessages {
  /** 通信エラー・HTTPエラー時のフォールバック（例:「天候情報の取得に失敗しました」）。 */
  failure: string;
  /** 成功応答のJSON解析に失敗したとき（例:「天候情報の解析に失敗しました」）。 */
  parseFailure: string;
}

export interface ApiRequestOptions {
  /** 既定はGET。bodyを指定するとContent-Type: application/jsonを自動で付ける。 */
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  /** タイムアウト（ミリ秒）。バックエンドがハングした場合に無期限に待たされるのを防ぐ。 */
  timeoutMs: number;
  /** DebugConsole上のカテゴリ（例: "api:weather"）。 */
  category: string;
  messages: ApiRequestMessages;
  /** 「リクエスト開始」ログの表題。メソッド・パスを出したいクライアントが上書きする。 */
  startLabel?: string;
  /** 開始ログにだけ載せる情報（urlは自動で載るため指定不要）。 */
  requestMeta?: Record<string, unknown>;
  /** 全ログ行へ載せる情報（同一カテゴリで複数エンドポイントを扱う場合のpath等）。 */
  logMeta?: Record<string, unknown>;
  /** 通信エラーを`messages.failure`で包み直すか（既定false＝元のErrorをそのまま投げる）。
   * 元の文言（"Failed to fetch"等）がそのまま画面へ出る呼び出し元だけtrueにする——
   * これも`messages`と同じ「文言をどう出すか」の選択で、骨格自体は分岐しない。 */
  wrapNetworkError?: boolean;
}

export interface ApiResponse {
  response: Response;
  durationMs: number;
  /** バックエンドが全リクエストへ付与するリクエストID
   * （backend/app/infrastructure/request_log.py）。サーバーログとの突き合わせに使う。 */
  requestId: string | null;
}

/** APIがエラー応答を返したときに投げる。リクエストIDは開発者向け（デバッグログ・
 * BackendLogsPanel）の情報で、画面へ出す`message`には含めない——利用者には意味が無く、
 * 文言が長くなるぶん狭い幅のレイアウトを壊す。 */
export class ApiError extends Error {
  readonly requestId: string | null;
  readonly status: number | null;

  constructor(message: string, requestId: string | null = null, status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.requestId = requestId;
    this.status = status;
  }
}

/** 7段のうち「fetch→通信エラー処理→ok確認→失敗時throw」まで。成功時の`Response`を
 * そのまま返し、本文の解釈と成功ログは呼び出し側が行う。 */
export async function requestOk(url: string, options: ApiRequestOptions): Promise<ApiResponse> {
  const { method = "GET", body, timeoutMs, category, messages, startLabel, requestMeta, logMeta, wrapNetworkError } = options;
  const startedAt = performance.now();
  const meta = { ...logMeta };
  debugLog(category, startLabel ?? "リクエスト開始", { url, ...meta, ...requestMeta });

  // fetch()自体の失敗（バックエンド到達不能等の通信エラー）はresponse.okのチェック以前の
  // 例外として送出されるため、ここで捕まえずにいると失敗がデバッグログに一切残らない。
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      ...(body !== undefined ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    // AbortSignal.timeout由来の中断はDOMException("TimeoutError")として送出される
    // （fetch仕様）ため、タイムアウトかそれ以外の通信エラーかをログで区別する。
    const isTimeout = error instanceof DOMException && error.name === "TimeoutError";
    // error.cause: ブラウザによっては（常にではない）fetch失敗の追加ヒントが入ることがある。
    // ただしCORS/CSP/拡張機能ブロック等の「本当の理由」はセキュリティ上の理由でfetch()の
    // 仕様としてJSへ一切渡されないため、これを足しても取れないケースの方が多い——その場合の
    // 唯一の手掛かりはブラウザ自身が出すネイティブなコンソールログ（アプリのdebugLogとは別）。
    const cause = error instanceof Error && "cause" in error ? (error as { cause?: unknown }).cause : undefined;
    debugLog(
      category,
      isTimeout ? `失敗 (タイムアウト ${timeoutMs}ms)` : "失敗 (通信エラー)",
      {
        ...meta,
        durationMs: Math.round(performance.now() - startedAt),
        error: error instanceof Error ? `${error.name}: ${error.message}` : String(error),
        ...(cause !== undefined ? { cause: String(cause) } : {}),
      },
      "error",
    );
    const detail = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    if (wrapNetworkError) throw new Error(`${messages.failure}: ${detail}`, { cause: error });
    // Error以外が投げられた場合だけ、失った情報を文言へ残す（fetchは通常Error/DOMException
    // を投げるため実際にはほぼ通らない経路）。
    throw error instanceof Error ? error : new Error(`${messages.failure}: ${detail}`);
  }
  const durationMs = Math.round(performance.now() - startedAt);
  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog(category, `失敗 (HTTP ${response.status})`, { ...meta, durationMs, requestId, errorBody }, "error");
    const detail = formatErrorDetail(errorBody?.detail) ?? `${messages.failure}[HTTP ${response.status}]`;
    throw new ApiError(detail, requestId, response.status);
  }
  return { response, durationMs, requestId };
}

/** `requestOk`＋JSON解析＋成功ログ。204 No Contentは`undefined`を返す
 * （本文を持たない削除系エンドポイント向け）。 */
export async function requestJson<T>(url: string, options: ApiRequestOptions): Promise<T> {
  const { response, durationMs, requestId } = await requestOk(url, options);
  const meta = { ...options.logMeta };

  if (response.status === 204) {
    debugLog(options.category, "成功", { ...meta, durationMs, requestId });
    return undefined as T;
  }

  let data: T;
  try {
    data = await response.json();
  } catch {
    debugLog(options.category, "失敗 (不正なレスポンス)", { ...meta, durationMs, requestId }, "error");
    throw new Error(options.messages.parseFailure);
  }
  debugLog(options.category, "成功", { ...meta, durationMs, requestId });
  return data;
}

export interface FetchJsonOptions {
  /** タイムアウト（ミリ秒）。 */
  timeoutMs: number;
  /** DebugConsole上のカテゴリ（例: "api:weather"）。 */
  category: string;
  /** エラーメッセージの生成に使う対象名。「{errorLabel}の取得に失敗しました」
   * 「{errorLabel}の解析に失敗しました」の形で使われる。 */
  errorLabel: string;
  /** 「リクエスト開始」ログへ追加で載せたい情報（urlは自動で載るため指定不要）。 */
  requestMeta?: Record<string, unknown>;
}

/** `errorLabel`から「◯◯の取得/解析に失敗しました」を組み立てる。GET系クライアントは
 * この1つの文言体系を共有する。 */
export function getMessages(errorLabel: string): ApiRequestMessages {
  return { failure: `${errorLabel}の取得に失敗しました`, parseFailure: `${errorLabel}の解析に失敗しました` };
}

/** GET専用のfetch共通ラッパー（`requestJson`の薄い糖衣）。 */
export async function fetchJson<T>(url: string, options: FetchJsonOptions): Promise<T> {
  return requestJson<T>(url, {
    timeoutMs: options.timeoutMs,
    category: options.category,
    messages: getMessages(options.errorLabel),
    requestMeta: options.requestMeta,
  });
}
