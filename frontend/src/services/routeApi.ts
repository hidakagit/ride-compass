import type {
  GenerationConditions,
  RouteCandidate,
  RouteGenerateJobCreatedResponse,
  RouteGenerateJobStatusResponse,
  RouteGenerateRequest,
  RoutePreviewRequest,
  RouteSegment,
} from "@/types/route";
import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";
import { fetchJson } from "@/lib/fetchJson";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function postJson<T>(path: string, body: unknown, timeoutMs: number): Promise<T> {
  const startedAt = performance.now();
  debugLog("api:route", `POST ${path}`, { body });

  // fetch()自体の失敗（タイムアウト・バックエンド到達不能等の通信エラー）はresponse.okの
  // チェック以前の例外として送出されるため、ここで捕まえずにいると失敗がデバッグログに
  // 一切残らない（lib/fetchJson.tsのGET用実装と同じパターン、T105調査で確立。実機で
  // 「20kmルート生成がfail to fetchで失敗するが原因がログから追えない」という報告を
  // 受けて2026-08-24にPOST側にも適用）。AbortSignal.timeout由来の中断は
  // DOMException("TimeoutError")として送出される（fetch仕様）ため、タイムアウトか
  // それ以外の通信エラーかをログで区別できるようにする。
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    const isTimeout = error instanceof DOMException && error.name === "TimeoutError";
    // error.cause: ブラウザによっては（常にではない）fetch失敗の追加ヒントが入ることがある。
    // ただしCORS/CSP/拡張機能ブロック等の「本当の理由」はセキュリティ上の理由でfetch()の
    // 仕様としてJSへ一切渡されないため、これを足しても取れないケースの方が多い——その場合の
    // 唯一の手掛かりはブラウザ自身が出すネイティブなコンソールログ（アプリのdebugLogとは別)。
    const cause = error instanceof Error && "cause" in error ? (error as { cause?: unknown }).cause : undefined;
    debugLog(
      "api:route",
      isTimeout ? `失敗 (タイムアウト ${timeoutMs}ms)` : "失敗 (通信エラー)",
      {
        path,
        durationMs: Math.round(performance.now() - startedAt),
        error: error instanceof Error ? `${error.name}: ${error.message}` : String(error),
        ...(cause !== undefined ? { cause: String(cause) } : {}),
      },
      "error",
    );
    throw error instanceof Error
      ? error
      : new Error(`リクエストに失敗しました: ${String(error)}`);
  }
  const durationMs = Math.round(performance.now() - startedAt);
  // バックエンドが全リクエストに付与するリクエストID(backend/app/infrastructure/request_log.py)。
  // サーバーログと突き合わせるためDebugConsoleと失敗時のエラーメッセージに含める。
  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog("api:route", `失敗 (HTTP ${response.status})`, { path, durationMs, requestId, errorBody }, "error");
    const detail = formatErrorDetail(errorBody?.detail) ?? `リクエストに失敗しました[HTTP ${response.status}]`;
    throw new Error(requestId ? `${detail}[req: ${requestId}]` : detail);
  }

  let data: T;
  try {
    data = await response.json();
  } catch {
    debugLog("api:route", "失敗 (不正なレスポンス)", { path, durationMs, requestId }, "error");
    throw new Error("サーバーからの応答の解析に失敗しました");
  }
  debugLog("api:route", "成功", { path, durationMs, requestId });
  return data;
}

export async function previewRoute(request: RoutePreviewRequest): Promise<RouteSegment> {
  return postJson<RouteSegment>("/api/routes/preview", request, 15000);
}

export interface GenerateRoutesResult {
  routes: RouteCandidate[];
  conditions: GenerationConditions;
  engine: string;
}

/** ルート生成の進捗（改善計画T265）。プロパティの粒度は「待ち/実行中」＋フロント側で
 * 計算する経過時間のみ（prepare/trace/evaluateのステージ別進捗はエンジン内部への
 * 侵襲的な変更が要るため対象外、docs/tasks/T265.md参照）。 */
export interface GenerationProgress {
  status: "queued" | "running";
  elapsedMs: number;
}

const POLL_INTERVAL_MS = 1500;
// road_graphエンジンの冷パスは、バックエンドのDBコマンドタイムアウト
// (ROUTE_GENERATION_COMMAND_TIMEOUT_SECONDS=180秒、backend/app/infrastructure/database.py)
// より短いとポーリングが先に諦めてしまう(改善計画T248で発覚)。本番実測の最悪ケース
// (王子30km、save_graphのバルクUPSERT込みでtotal_ms=315,859≒316秒)を安全マージン込みで
// 上回る値にする。以前は単発fetchのAbortSignal.timeoutだったが、改善計画T265で
// ポーリングの総待ち時間上限へ役割が変わった（値自体は据え置き）。
const MAX_POLL_DURATION_MS = 360000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** ルート生成ジョブの状態を1回取得する（改善計画T265）。GET専用の共通ラッパー
 * （lib/fetchJson.ts、他のGET系APIクライアントと同じパターン）を使う。 */
function pollGenerationJob(jobId: string): Promise<RouteGenerateJobStatusResponse> {
  return fetchJson<RouteGenerateJobStatusResponse>(`${API_BASE_URL}/api/routes/generate/${jobId}`, {
    timeoutMs: 15000,
    category: "api:route",
    errorLabel: "ルート生成の状態",
    requestMeta: { jobId },
  });
}

/** ルート生成（改善計画T265でバックグラウンドジョブ化）。`POST /api/routes/generate`は
 * 即座（数百ms）にjob_idを返すため、`GET /api/routes/generate/{job_id}`をポーリングして
 * 完了を待つ。`onProgress`は待ち(queued)/実行中(running)の間、ポーリングのたびに
 * 呼ばれる（呼び出し側のUI表示用、省略可）。 */
export async function generateRoutes(
  request: RouteGenerateRequest,
  onProgress?: (progress: GenerationProgress) => void,
): Promise<GenerateRoutesResult> {
  const { job_id: jobId } = await postJson<RouteGenerateJobCreatedResponse>(
    "/api/routes/generate", request, 15000,
  );
  const startedAt = performance.now();

  for (;;) {
    const elapsedMs = performance.now() - startedAt;
    if (elapsedMs > MAX_POLL_DURATION_MS) {
      debugLog("api:route", "失敗 (ポーリングタイムアウト)", { jobId, elapsedMs }, "error");
      throw new Error("ルート生成がタイムアウトしました");
    }
    await sleep(POLL_INTERVAL_MS);
    const status = await pollGenerationJob(jobId);
    if (status.status === "done") {
      if (!status.result) {
        // 型上はstatus"done"でもresultがnullでありうる（RouteGenerateJobStatusResponse.
        // result: RouteGenerateResponse | None）。backend側は常にresultと同時にdoneへ
        // 遷移させる設計だが、万一の不整合を無視して先へ進めるよりは明示的に失敗させる。
        throw new Error("ルート生成が完了しましたが結果を取得できませんでした");
      }
      const result = status.result;
      debugLog("api:route", `ルーティングエンジン: ${result.engine}`, { count: result.routes.length });
      // conditionsは実験スロット（比較・再現用、研究インターフェース改善 §10-3/6）の入力になる。
      return { routes: result.routes, conditions: result.conditions, engine: result.engine };
    }
    if (status.status === "failed") {
      throw new Error(status.error ?? "ルート生成に失敗しました");
    }
    onProgress?.({ status: status.status, elapsedMs });
  }
}
