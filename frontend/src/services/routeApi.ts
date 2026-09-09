import type {
  GenerationConditions,
  RouteCandidate,
  RouteGenerateJobCreatedResponse,
  RouteGenerateJobStatusResponse,
  RouteGenerateRequest,
} from "@/types/route";
import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { debugLog } from "@/lib/debugLog";
import { fetchJson, requestJson } from "@/lib/fetchJson";
import { DEFAULT_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

/** ルート生成系のPOST。エラー文言はエンドポイントごとに動詞が変わる（生成・取得等）ため
 * 「リクエストに失敗しました」で統一し、詳細はbackendのdetailに委ねる。 */
async function postJson<T>(path: string, body: unknown, timeoutMs: number): Promise<T> {
  return requestJson<T>(`${API_BASE_URL}${path}`, {
    method: "POST",
    body,
    timeoutMs,
    category: "api:route",
    messages: { failure: "リクエストに失敗しました", parseFailure: "サーバーからの応答の解析に失敗しました" },
    startLabel: `POST ${path}`,
    requestMeta: { body },
    logMeta: { path },
  });
}

export interface GenerateRoutesResult {
  routes: RouteCandidate[];
  conditions: GenerationConditions;
  engine: string;
  /** routesが空のときの原因（backend: RouteGenerator.last_no_candidates_reason）。
   * SSHでサーバーログを見なくても、GUI（呼び出し側のエラーメッセージ・デバッグログ）まで
   * 届ける。 */
  noCandidatesReason?: string;
}

/** ルート生成の進捗。プロパティの粒度は「待ち/実行中」＋フロント側で計算する経過時間
 * のみ（prepare/trace/evaluateのステージ別進捗はエンジン内部への侵襲的な変更が要るため
 * 対象外）。 */
export interface GenerationProgress {
  status: "queued" | "running";
  elapsedMs: number;
}

const POLL_INTERVAL_MS = 1500;
// road_graphエンジンの冷パス（未split・タイル未キャッシュ）の総所要時間（total_ms）を
// 安全マージン込みで上回る値にする。開発機実測の最悪ケース（都心部、prepare_ms=355,516・
// total_ms=360,625）が示すとおり、prepare_ms単体で数分規模になりうる（開発機のリソース
// 競合で本番より悪化するが、本番でも同種の遅さ自体は再現する）。DBの
// ROUTE_GENERATION_COMMAND_TIMEOUT_SECONDS（180秒、backend/app/infrastructure/
// database.py）はクエリ1本ごとの上限でありprepare()全体の所要時間とは独立のため、
// この値の決定には関与しない。
const MAX_POLL_DURATION_MS = 600000;
// 1回のポーリング失敗（一時的なネットワーク瞬断・5xx）で生成全体を即座に失敗させず、
// この回数まで連続失敗を許容してから
// 諦める。バックエンド側`_run_generate_job`はジョブをキャンセルする手段が無く握ったままの
// ため、早すぎる諦めは同時実行枠（既定2）を無駄に占有させる孤立ジョブを生みやすい一方、
// 諦めが遅すぎても本当に接続が切れているケースの検知が遅れるため、POLL_INTERVAL_MS込みで
// 数十秒程度（5回×1.5秒間隔）に収める。
const MAX_CONSECUTIVE_POLL_FAILURES = 5;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** ルート生成ジョブの状態を1回取得する。GET専用の共通ラッパー
 * （lib/fetchJson.ts、他のGET系APIクライアントと同じパターン）を使う。 */
function pollGenerationJob(jobId: string): Promise<RouteGenerateJobStatusResponse> {
  return fetchJson<RouteGenerateJobStatusResponse>(`${API_BASE_URL}/api/routes/generate/${jobId}`, {
    timeoutMs: DEFAULT_API_TIMEOUT_MS,
    category: "api:route",
    errorLabel: "ルート生成の状態",
    requestMeta: { jobId },
  });
}

/** ルート生成はバックグラウンドジョブ化されている。`POST /api/routes/generate`は
 * 即座（数百ms）にjob_idを返すため、`GET /api/routes/generate/{job_id}`をポーリングして
 * 完了を待つ。`onProgress`は待ち(queued)/実行中(running)の間、ポーリングのたびに
 * 呼ばれる（呼び出し側のUI表示用、省略可）。 */
export async function generateRoutes(
  request: RouteGenerateRequest,
  onProgress?: (progress: GenerationProgress) => void,
): Promise<GenerateRoutesResult> {
  const { job_id: jobId } = await postJson<RouteGenerateJobCreatedResponse>(
    "/api/routes/generate", request, DEFAULT_API_TIMEOUT_MS,
  );
  const startedAt = performance.now();
  let consecutivePollFailures = 0;

  for (let pollCount = 0; ; pollCount += 1) {
    if (performance.now() - startedAt > MAX_POLL_DURATION_MS) {
      debugLog("api:route", "失敗 (ポーリングタイムアウト)", { jobId, elapsedMs: performance.now() - startedAt }, "error");
      throw new Error("ルート生成がタイムアウトしました");
    }
    // 初回だけsleepを挟まず即座にポーリングする。毎回ループ先頭でsleepすると、サーバー側の
    // 生成が数百ms〜1秒程度で終わる典型的なウォームパスでも必ずPOLL_INTERVAL_MS分待たされる。
    if (pollCount > 0) {
      await sleep(POLL_INTERVAL_MS);
    }

    let status: RouteGenerateJobStatusResponse;
    try {
      status = await pollGenerationJob(jobId);
      consecutivePollFailures = 0;
    } catch (error) {
      consecutivePollFailures += 1;
      // 1回の一時的な失敗では生成全体を落とさず、次のポーリングでリトライする。
      // この時点ではまだ「失敗が確定」していない（リトライで回復する可能性が高い）ため
      // "error"ではなく"warn"にする。5回連続で失敗し諦める場合は、この関数の呼び出し元
      // （page.tsx）が例外をcatchした時点で別途"error"として記録される。
      debugLog(
        "api:route",
        `ポーリング失敗、リトライします (${consecutivePollFailures}/${MAX_CONSECUTIVE_POLL_FAILURES})`,
        { jobId, error: error instanceof Error ? error.message : String(error) },
        "warn",
      );
      if (consecutivePollFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
        // AbortSignal.timeoutが送出する例外（DOMException「signal timed out」等の
        // ネイティブな英語メッセージ）をそのままthrowすると、呼び出し元（page.tsx）が
        // error.messageをそのまま画面へ表示するため、ユーザーに未翻訳の英語エラーが
        // 見えてしまう。MAX_POLL_DURATION_MS超過時と同じ方針で、人間可読な日本語
        // メッセージへ包み直す（元の例外はこの直前のdebugLogに残る）。
        debugLog(
          "api:route",
          "失敗 (ポーリング連続失敗で諦め)",
          { jobId, elapsedMs: performance.now() - startedAt },
          "error",
        );
        throw new Error("ルート生成の状況確認がネットワークの不調で繰り返し失敗しました。時間をおいて再度お試しください。");
      }
      continue;
    }

    // onProgressへ渡す経過時間はGETの応答が返った直後（＝実際に観測できた最新時点）で
    // 計算する。ループ先頭（sleep・GETの前）で計算すると、表示が常にPOLL_INTERVAL_MS+
    // GET応答時間ぶん遅れてしまう。
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
      // 候補0件の原因をwarnレベルで残す（デバッグモードでSSHを使わず確認できるように
      // する）。1件以上あれば`no_candidates_reason`は常にnull。
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
