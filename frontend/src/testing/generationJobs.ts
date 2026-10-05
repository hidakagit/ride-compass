// ルート生成のジョブ（`POST /api/routes/generate`と、そのジョブの状態の問い合わせ）の網の層の代役。出された生成に
// ジョブを割り当て、状態の問い合わせには、テストが積んだ答えを生成の出された順に1つずつ使って返す。
// 答えを積まずに出された生成は、代役が投げてテストを落とす（mswは投げた手引きを失敗として出す）。
import { heldReplies, onBackend, type SentRequest } from "@/testing/backendServer";
import type { GenerationConditions, RouteCandidate } from "@/types/route";

const GENERATE = "/api/routes/generate";

/** 1つのジョブの状態の問い合わせに答えるもの。問い合わせのたびに呼ぶ。 */
type JobReply = () => Response | Promise<Response>;

export function serveGenerationJobs() {
  const replies: JobReply[] = [];
  const jobs = new Map<string, JobReply>();
  const submitted: SentRequest[] = onBackend("POST", GENERATE, () => {
    const reply = replies.shift();
    if (!reply) throw new Error("生成の答えを積まずに生成が出された");
    const jobId = `job-${submitted.length}`;
    jobs.set(jobId, reply);
    return Response.json({ job_id: jobId });
  });
  onBackend("GET", `${GENERATE}/:jobId`, ({ path }) => jobs.get(path.split("/").at(-1) ?? "")!());

  return {
    /** 出された生成の要求（ジョブを作る要求なので、送ったものを確かめてよい）。 */
    submitted,
    /** 次の生成は、最初の問い合わせで終わって`routes`を返す。 */
    respond(routes: RouteCandidate[], conditions: GenerationConditions, noCandidatesReason?: string) {
      const result = { routes, conditions, no_candidates_reason: noCandidatesReason ?? null };
      replies.push(() => Response.json({ status: "done", result }));
    },
    /** 次の生成は、ジョブが`message`で失敗する。 */
    fail(message: string) {
      replies.push(() => Response.json({ status: "failed", error: message }));
    },
    /**
     * 次の生成は、状態の問い合わせに答えないまま（実行中のまま）にする。テストの終わりにジョブの失敗で閉じる——網の失敗で
     * 閉じると、生成の口が問い合わせを続け、後のテストの応答か応答の無い要求に当たる。
     */
    keepRunning() {
      replies.push(heldReplies(() => Response.json({ status: "failed", error: "テストが終わった" })).reply);
    },
    /** 次の生成の状態の問い合わせに`reply`で答える（待ち・実行中を挟むテスト用）。 */
    answerWith(reply: JobReply) {
      replies.push(reply);
    },
  };
}
