import type {
  GenerationConditions,
  RouteCandidate,
  RouteGenerateJobCreatedResponse,
  RouteGenerateJobStatusResponse,
  RouteGenerateRequest,
} from "@/types/route";
import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { apiPath, type DeclaredApiPath } from "@/lib/apiPath";
import { debugLog } from "@/lib/debugLog";
import { fetchJson, requestJson } from "@/lib/fetchJson";
import { DEFAULT_API_TIMEOUT_MS } from "@/lib/apiTimeouts";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

/** ルート生成系のPOST。エラー文言はエンドポイントごとに動詞が変わる（生成・取得等）ため
 * 「リクエストに失敗しました」で統一し、詳細はbackendのdetailに委ねる。 */
async function postJson<T>(path: DeclaredApiPath, body: unknown, timeoutMs: number): Promise<T> {
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
function pollGenerationJob(jobId: string): Promise<RouteGenerateJobStatusResponse> {
  return fetchJson<RouteGenerateJobStatusResponse>(
    `${API_BASE_URL}${apiPath("/api/routes/generate/{job_id}", { job_id: jobId })}`,
    {
      timeoutMs: DEFAULT_API_TIMEOUT_MS,
      category: "api:route",
      errorLabel: "ルート生成の状態",
      requestMeta: { jobId },
    },
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
  const { job_id: jobId } = await postJson<RouteGenerateJobCreatedResponse>(
    apiPath("/api/routes/generate"),
    request,
    DEFAULT_API_TIMEOUT_MS,
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
          `ルート生成の状況確認に続けて失敗しました${lastCause ? `（${lastCause}）` : ""}。時間をおいて再度お試しください。`,
          { cause: error },
        );
      }
      continue;
    }

    // 経過時間は応答が返った直後で測る（ループの先頭で測ると、表示が待ちと応答の時間ぶん遅れる）。
    const elapsedMs = performance.now() - startedAt;
    if (status.status === "done") {
      if (!status.result) {
        // 型の上では完了でも結果がnullでありうる。黙って進めず失敗にする。
        throw new Error("ルート生成が完了しましたが結果を取得できませんでした");
      }
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
      throw new Error(status.error ?? "ルート生成に失敗しました");
    }
    onProgress?.({ status: status.status, elapsedMs });
  }
}
