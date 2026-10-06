import type {
  GenerationConditions,
  RouteCandidate,
  RouteGenerateJobStatusResponse,
  RouteGenerateRequest,
} from "@/types/route";
import { backendApi, getOptions, requestApi } from "@/lib/apiClient";
import { debugLog } from "@/lib/debugLog";
import { DEFAULT_API_TIMEOUT_MS } from "@/lib/apiTimeouts";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

interface GenerateRoutesResult {
  routes: RouteCandidate[];
  conditions: GenerationConditions;
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
// backendがジョブの結果を持つ時間そのもの。これより長く待つと掃除済みのjob_idを引くため、
// 独立に値を持たない（値を動かすのはbackendの宣言側）。
const MAX_POLL_DURATION_MS = routeGenerateConfig.job_result_ttl_seconds * 1000;
// 続けて失敗してよい回数。backendはジョブを取り消せないので、早く諦めると同時実行の枠を孤立したジョブが占める。
// 遅すぎると本当に切れたときの検知が遅れるので、間隔と合わせて数十秒に収める。
const MAX_CONSECUTIVE_POLL_FAILURES = 5;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 生成のジョブの状態を1回取る。 */
async function pollGenerationJob(jobId: string): Promise<RouteGenerateJobStatusResponse> {
  return requestApi(
    (init) => backendApi.GET("/api/routes/generate/{job_id}", { params: { path: { job_id: jobId } }, ...init }),
    getOptions({ timeoutMs: DEFAULT_API_TIMEOUT_MS, category: "api:route", errorLabel: "ルート生成の状態" }),
  );
}

/** ルート生成はバックグラウンドジョブ化されている。`POST /api/routes/generate`は
 * 即座（数百ms）にjob_idを返すため、`GET /api/routes/generate/{job_id}`をポーリングして
 * 完了を待つ。`onProgress`は待ち(queued)/実行中(running)の間、ポーリングのたびに
 * 呼ばれる（呼び出し側のUI表示用、省略可）。 */
export async function generateRoutes(
  request: RouteGenerateRequest,
  onProgress?: (progress: GenerationProgress) => void,
): Promise<GenerateRoutesResult> {
  // 文言は失敗したことと次の手に留め、詳細はbackendのdetailに委ねる。
  const { job_id: jobId } = await requestApi(
    (init) => backendApi.POST("/api/routes/generate", { body: request, ...init }),
    {
      timeoutMs: DEFAULT_API_TIMEOUT_MS,
      category: "api:route",
      messages: {
        failure: "リクエストに失敗しました。時間をおいて再度お試しください",
        parseFailure: "サーバーからの応答の解析に失敗しました",
      },
      requestMeta: { body: request },
    },
  );
  const startedAt = performance.now();
  let consecutivePollFailures = 0;

  for (let pollCount = 0; ; pollCount += 1) {
    if (performance.now() - startedAt > MAX_POLL_DURATION_MS) {
      debugLog(
        "api:route",
        "失敗 (ポーリングタイムアウト)",
        { jobId, elapsedMs: performance.now() - startedAt },
        "error",
      );
      throw new Error("ルート生成がタイムアウトしました");
    }
    // 初回は待たずに問い合わせる（1秒足らずで終わる生成を毎回待たせない）。
    if (pollCount > 0) {
      await sleep(POLL_INTERVAL_MS);
    }

    let status: RouteGenerateJobStatusResponse;
    try {
      status = await pollGenerationJob(jobId);
      consecutivePollFailures = 0;
    } catch (error) {
      consecutivePollFailures += 1;
      // 一時の失敗は次の問い合わせで取り直す（まだ失敗が決まっていないのでwarn）。
      debugLog(
        "api:route",
        `ポーリング失敗、リトライします (${consecutivePollFailures}/${MAX_CONSECUTIVE_POLL_FAILURES})`,
        { jobId, error: error instanceof Error ? error.message : String(error) },
        "warn",
      );
      if (consecutivePollFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
        debugLog(
          "api:route",
          "失敗 (ポーリング連続失敗で諦め)",
          { jobId, elapsedMs: performance.now() - startedAt },
          "error",
        );
        // 原因（通信・混雑・ジョブの消失）は断定せず、最後の失敗の文言を添える。
        const lastCause = error instanceof Error ? error.message.replace(/。$/, "") : null;
        throw new Error(
          `ルート生成の状況確認に続けて失敗しました${lastCause ? `: ${lastCause}` : ""}。時間をおいて再度お試しください。`,
          { cause: error },
        );
      }
      continue;
    }

    // 経過時間は応答が返った直後で測る（ループの先頭で測ると、表示が待ちと応答の時間ぶん遅れる）。
    const elapsedMs = performance.now() - startedAt;
    if (status.status === "done") {
      const result = status.result;
      debugLog("api:route", `候補 ${result.routes.length}件`, { jobId });
      // 候補0件の原因を残す（サーバーのログを見に行かずに分かるように）。
      if (result.routes.length === 0 && result.no_candidates_reason) {
        debugLog("api:route", result.no_candidates_reason, { jobId }, "warn");
      }
      return {
        routes: result.routes,
        conditions: result.conditions,
        noCandidatesReason: result.no_candidates_reason ?? undefined,
      };
    }
    if (status.status === "failed") {
      throw new Error(status.error);
    }
    onProgress?.({ status: status.status, elapsedMs });
  }
}
