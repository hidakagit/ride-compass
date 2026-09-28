import createClient, { type Middleware } from "openapi-fetch";

import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";
import type { paths } from "@/types/generated/api";

// backendのAPIを呼ぶ口と、全呼び出しが共有する骨格（開始・通信の失敗・HTTPの失敗・解析の失敗・成功をdebugLogへ残し、
// 失敗を日本語の文言の`Error`で投げる）。パス・問い合わせ・本文・応答の型はopenapi-fetchがOpenAPIの生成物から推論する。

/** 呼ぶたびに`globalThis.fetch`を引く（作った時点の関数を握ると、差し替えた`fetch`が届かない）。 */
const fetchNow = (request: Request) => fetch(request);

/** backendを直接呼ぶ口。 */
export const backendApi = createClient<paths>({ baseUrl: API_BASE_URL, fetch: fetchNow });

/** backendの管理API`/api/admin<X>`だけを持つ契約。管理画面は同一オリジンの口`/admin/api<X>`を叩く
 * （`app/admin/api/[...path]/route.ts`。/adminのBasic認証をそのまま使う）。 */
type AdminPaths = { [P in keyof paths as P extends `/api/admin${infer Rest}` ? Rest : never]: paths[P] };

/** 管理APIを同一オリジンの口経由で呼ぶ口。パスはbackendのパスの`/api/admin`より後。 */
export const adminApiClient = createClient<AdminPaths>({ baseUrl: "/admin/api", fetch: fetchNow });

/** 応答の形がbackendの契約に無い口（気象庁の配信をそのまま返す転送・フロント自身のroute handler）。 */
type UndeclaredPaths = Record<
  string,
  { get: { parameters: { query?: never }; responses: { 200: { content: { "application/json": unknown } } } } }
>;
const undeclaredApi = createClient<UndeclaredPaths>({ fetch: fetchNow });

/** エラー時に利用者へ見せる文言。HTTPエラーでbackendが`detail`を返せばそちらを優先する。 */
interface ApiRequestMessages {
  /** 通信エラー・HTTPエラー時のフォールバック（例:「天候情報の取得に失敗しました」）。 */
  failure: string;
  /** 成功応答のJSON解析に失敗したとき（例:「天候情報の解析に失敗しました」）。 */
  parseFailure: string;
}

interface ApiRequestOptions<D> {
  /** タイムアウト（ミリ秒）。バックエンドがハングした場合に無期限に待たされるのを防ぐ。 */
  timeoutMs: number;
  /** DebugConsole上のカテゴリ（例: "api:weather"）。 */
  category: string;
  messages: ApiRequestMessages;
  /** 開始ログにだけ載せる情報（メソッドとurlは自動で載る）。 */
  requestMeta?: Record<string, unknown>;
  /** 成功ログへ足す情報（応答から数えた件数等）。 */
  successMeta?: (data: D) => Record<string, unknown>;
}

/** 呼び出し口（`backendApi.GET`等）が返すもの。 */
interface ApiResult {
  data?: unknown;
  error?: unknown;
  response: Response;
}

type DataOf<R> = R extends { data: infer D } ? D : never;

/** 呼び出しに骨格が渡すもの。呼び出し口の第2引数へ展開する（呼び出し口が任意の項目を受ける型なので`type`で書く）。 */
type SkeletonInit = {
  signal: AbortSignal;
  middleware: Middleware[];
};

/** 応答が失敗の状態で返った。状態で振る舞いを分ける呼び出し元（配信元がまだ出していないコマの404等）が`status`を読む。 */
export class HttpStatusError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "HttpStatusError";
    this.status = status;
  }
}

function errorDetail(body: unknown): unknown {
  return body !== null && typeof body === "object" && "detail" in body ? body.detail : undefined;
}

/**
 * `send`の呼び出しを骨格で包み、成功した応答の本体を返す。失敗は常に日本語の文言の`Error`で投げる。
 *
 * 通信エラー・タイムアウトは`messages.failure`へ`[通信エラー]`/`[タイムアウト]`を添えて包み直し、ブラウザ由来の英語の
 * 文言（"Failed to fetch"・"signal timed out"）は`cause`とdebugLogにだけ残す——呼び出し元の多くは`message`をそのまま
 * 画面へ出す。`x-request-id`は失敗のログに残し、画面へ出す文言には混ぜない。
 */
export async function requestApi<R extends ApiResult>(
  send: (init: SkeletonInit) => Promise<R>,
  options: ApiRequestOptions<DataOf<R>>,
): Promise<DataOf<R>> {
  const { timeoutMs, category, messages, requestMeta, successMeta } = options;
  const startedAt = performance.now();
  const elapsedMs = () => Math.round(performance.now() - startedAt);
  const seen = { url: "", responded: false };

  const skeleton: Middleware = {
    onRequest({ request }) {
      seen.url = request.url;
      debugLog(category, "リクエスト開始", { method: request.method, url: request.url, ...requestMeta });
    },
    onResponse() {
      seen.responded = true;
    },
    onError({ error }) {
      // AbortSignal.timeout由来の中断はDOMException("TimeoutError")として送出される（fetch仕様）。
      const isTimeout = error instanceof DOMException && error.name === "TimeoutError";
      // error.cause: ブラウザによっては（常にではない）fetch失敗の追加ヒントが入ることがある。
      // ただしCORS/CSP/拡張機能ブロック等の「本当の理由」はセキュリティ上の理由でfetch()の
      // 仕様としてJSへ一切渡されないため、これを足しても取れないケースの方が多い——その場合の
      // 唯一の手掛かりはブラウザ自身が出すネイティブなコンソールログ（アプリのdebugLogとは別）。
      const cause = error instanceof Error && "cause" in error ? error.cause : undefined;
      debugLog(
        category,
        isTimeout ? `失敗 (タイムアウト ${timeoutMs}ms)` : "失敗 (通信エラー)",
        {
          url: seen.url,
          durationMs: elapsedMs(),
          error: error instanceof Error ? `${error.name}: ${error.message}` : String(error),
          ...(cause !== undefined ? { cause: String(cause) } : {}),
        },
        "error",
      );
      return new Error(`${messages.failure}[${isTimeout ? "タイムアウト" : "通信エラー"}]`, { cause: error });
    },
  };

  let result: R;
  try {
    result = await send({ signal: AbortSignal.timeout(timeoutMs), middleware: [skeleton] });
  } catch (error) {
    // 応答が届く前の失敗は`onError`が包み直してある。届いた後に投げられるのは本文の解析の失敗だけ。
    if (!seen.responded) throw error;
    debugLog(category, "失敗 (不正なレスポンス)", { url: seen.url, durationMs: elapsedMs() }, "error");
    throw new Error(messages.parseFailure, { cause: error });
  }

  const { response } = result;
  const fields = { url: seen.url, durationMs: elapsedMs(), requestId: response.headers.get("x-request-id") };
  if (!response.ok) {
    debugLog(category, `失敗 (HTTP ${response.status})`, { ...fields, errorBody: result.error }, "error");
    throw new HttpStatusError(
      formatErrorDetail(errorDetail(result.error)) ?? `${messages.failure}[HTTP ${response.status}]`,
      response.status,
    );
  }
  const data = result.data as DataOf<R>;
  debugLog(category, "成功", { ...fields, ...successMeta?.(data) });
  return data;
}

interface GetOptions extends Omit<ApiRequestOptions<unknown>, "messages" | "successMeta"> {
  /** 「{errorLabel}の取得に失敗しました」「{errorLabel}の解析に失敗しました」の主語。 */
  errorLabel: string;
}

/** 取得（GET）の骨格の設定。文言を`errorLabel`から組み立て、取得はこの1つの文言体系を共有する。 */
export function getOptions({ errorLabel, ...options }: GetOptions): ApiRequestOptions<unknown> {
  return {
    ...options,
    messages: { failure: `${errorLabel}の取得に失敗しました`, parseFailure: `${errorLabel}の解析に失敗しました` },
  };
}

/** 応答の形が契約に無いURLをGETする（`T`は呼び出し側の約束で、検査されない）。契約にある口は`backendApi`で呼ぶ。 */
export async function fetchJson<T>(url: string, options: GetOptions): Promise<T> {
  const data = await requestApi((init) => undeclaredApi.GET(url, init), getOptions(options));
  return data as T;
}
