import type {
  GenerationConditions,
  RouteCandidate,
  RouteGenerateJobCreatedResponse,
  RouteGenerateJobStatusResponse,
  RouteGenerateRequest,
  RoutePreviewRequest,
  RouteSegment,
} from "@/types/route";
import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";
import { fetchJson } from "@/lib/fetchJson";

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
  /** 改善計画T441: routesが空のときの原因（backend: RouteGenerator.
   * last_no_candidates_reason）。SSHでサーバーログを見ないと原因が分からなかった
   * 実インシデントを受け、GUI（呼び出し側のエラーメッセージ・デバッグログ）まで届ける。 */
  noCandidatesReason?: string;
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
// 改善計画T386（T265コードレビュー指摘2件目、CONFIRMED）: 1回のポーリング失敗（一時的な
// ネットワーク瞬断・5xx）で生成全体を即座に失敗させず、この回数まで連続失敗を許容してから
// 諦める。バックエンド側`_run_generate_job`はジョブをキャンセルする手段が無く握ったままの
// ため、早すぎる諦めは同時実行枠（既定2）を無駄に占有させる孤立ジョブを生みやすい一方、
// 諦めが遅すぎても本当に接続が切れているケースの検知が遅れるため、POLL_INTERVAL_MS込みで
// 数十秒程度（5回×1.5秒間隔）に収める。
const MAX_CONSECUTIVE_POLL_FAILURES = 5;

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
  let consecutivePollFailures = 0;

  for (let pollCount = 0; ; pollCount += 1) {
    if (performance.now() - startedAt > MAX_POLL_DURATION_MS) {
      debugLog("api:route", "失敗 (ポーリングタイムアウト)", { jobId, elapsedMs: performance.now() - startedAt }, "error");
      throw new Error("ルート生成がタイムアウトしました");
    }
    // 改善計画T386（T265コードレビュー指摘6件目、CONFIRMED）: 初回だけsleepを挟まず
    // 即座にポーリングする。以前は毎回ループ先頭でsleepしていたため、サーバー側の生成が
    // 数百ms〜1秒程度で終わる典型的なウォームパスでも必ずPOLL_INTERVAL_MS分待たされていた。
    if (pollCount > 0) {
      await sleep(POLL_INTERVAL_MS);
    }

    let status: RouteGenerateJobStatusResponse;
    try {
      status = await pollGenerationJob(jobId);
      consecutivePollFailures = 0;
    } catch (error) {
      consecutivePollFailures += 1;
      // 改善計画T386（T265コードレビュー指摘2件目、CONFIRMED）: 1回の一時的な失敗では
      // 生成全体を落とさず、次のポーリングでリトライする。改善計画T441:
      // この時点ではまだ「失敗が確定」していない（リトライで回復する可能性が高い、
      // 実際に本番でtimeoutの直後に成功した実績がある）ため"error"ではなく"warn"にする。
      // 5回連続で失敗し諦める場合は、この関数の呼び出し元（page.tsx）が例外を
      // catchした時点で別途"error"として記録される。
      debugLog(
        "api:route",
        `ポーリング失敗、リトライします (${consecutivePollFailures}/${MAX_CONSECUTIVE_POLL_FAILURES})`,
        { jobId, error: error instanceof Error ? error.message : String(error) },
        "warn",
      );
      if (consecutivePollFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
        throw error instanceof Error ? error : new Error("ルート生成の状態取得に失敗しました");
      }
      continue;
    }

    // 改善計画T386（T265コードレビュー指摘8件目、CONFIRMED）: onProgressへ渡す経過時間は
    // GETの応答が返った直後（＝実際に観測できた最新時点）で計算する。以前はループ先頭
    // （sleep・GETの前）で計算していたため、表示が常にPOLL_INTERVAL_MS+GET応答時間ぶん
    // 遅れていた。
    const elapsedMs = performance.now() - startedAt;
    if (status.status === "done") {
      if (!status.result) {
        // 型上はstatus"done"でもresultがnullでありうる（RouteGenerateJobStatusResponse.
        // result: RouteGenerateResponse | None）。backend側は常にresultと同時にdoneへ
        // 遷移させる設計だが、万一の不整合を無視して先へ進めるよりは明示的に失敗させる。
        throw new Error("ルート生成が完了しましたが結果を取得できませんでした");
      }
      const result = status.result;
      debugLog("api:route", `ルーティングエンジン: ${result.engine}`, { count: result.routes.length });
      // 改善計画T441: 候補0件の原因をwarnレベルで残す（デバッグモードでSSHを使わず
      // 確認できるようにする）。1件以上あれば`no_candidates_reason`は常にnull。
      if (result.routes.length === 0 && result.no_candidates_reason) {
        debugLog("api:route", result.no_candidates_reason, { jobId }, "warn");
      }
      // conditionsは実験スロット（比較・再現用、研究インターフェース改善 §10-3/6）の入力になる。
      return {
        routes: result.routes,
        conditions: result.conditions,
        engine: result.engine,
        noCandidatesReason: result.no_candidates_reason ?? undefined,
      };
    }
    if (status.status === "failed") {
      throw new Error(status.error ?? "ルート生成に失敗しました");
    }
    onProgress?.({ status: status.status, elapsedMs });
  }
}
