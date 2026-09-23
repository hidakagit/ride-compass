// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeResponse } from "@/testing/fetchMocks";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { RouteGenerateRequest } from "@/types/route";

import { generateRoutes } from "./routeApi";

// backendの生成はジョブで、POSTがjob_idを返し、GETで結果を問い合わせる。
// 1回ごとの応答は`respond`へ並べ、fetchは並んだ順に返す（尽きたら最後の応答を返し続ける）。
type Step = { json: unknown } | { status: number } | { reject: Error };
let steps: Step[];
let calls: { url: string; init: RequestInit }[];

const REQUEST = { latitude: 35.6, longitude: 139.7, distance_km: 20 } as RouteGenerateRequest;
const DONE = {
  status: "done",
  result: { routes: [{ id: "r1" }], conditions: { distance_km: 20 }, no_candidates_reason: null },
};

function respond(...next: Step[]) {
  steps = next;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance", "Date"] });
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      const step = steps.length > 1 ? steps.shift()! : steps[0];
      if ("reject" in step) throw step.reject;
      if ("status" in step) return makeResponse({ ok: false, status: step.status, json: async () => ({}) });
      return makeResponse({ json: async () => step.json });
    }),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** 生成を始め、fetchが返るたびにタイマーを進めて最後まで回す。 */
async function run(onProgress?: Parameters<typeof generateRoutes>[1]) {
  const promise = generateRoutes(REQUEST, onProgress);
  promise.catch(() => {});
  await vi.runAllTimersAsync();
  return promise;
}

const polls = () => calls.filter((call) => call.init.method === "GET" || call.init.method === undefined);

describe("generateRoutes", () => {
  it("ジョブを投稿し、そのjob_idの結果を問い合わせて、候補と生成条件を返す", async () => {
    respond({ json: { job_id: "job-7" } }, { json: DONE });
    const result = await run();

    expect(calls[0].url).toMatch(/\/api\/routes\/generate$/);
    expect(calls[0].init.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init.body))).toEqual(REQUEST);
    expect(calls[1].url).toMatch(/\/api\/routes\/generate\/job-7$/);
    expect(result).toEqual({ routes: [{ id: "r1" }], conditions: { distance_km: 20 }, noCandidatesReason: undefined });
  });

  it("候補が0件なら、その理由を返す", async () => {
    const empty = { status: "done", result: { routes: [], conditions: {}, no_candidates_reason: "候補がありません" } };
    respond({ json: { job_id: "j" } }, { json: empty });
    await expect(run()).resolves.toMatchObject({ routes: [], noCandidatesReason: "候補がありません" });
  });

  it("最初の問い合わせは待たずに行い、以降は1.5秒おきに問い合わせる", async () => {
    respond({ json: { job_id: "j" } }, { json: { status: "queued" } }, { json: { status: "running" } }, { json: DONE });
    const promise = generateRoutes(REQUEST);
    await vi.advanceTimersByTimeAsync(0);
    expect(polls()).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1499);
    expect(polls()).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(polls()).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1500);
    await expect(promise).resolves.toMatchObject({ routes: [{ id: "r1" }] });
  });

  it("待ち・実行中の間は、問い合わせのたびに状態と経過時間を知らせる", async () => {
    respond({ json: { job_id: "j" } }, { json: { status: "queued" } }, { json: { status: "running" } }, { json: DONE });
    const progress: { status: string; elapsedMs: number }[] = [];
    await run((p) => progress.push(p));
    expect(progress.map((p) => p.status)).toEqual(["queued", "running"]);
    expect(progress[1].elapsedMs).toBeGreaterThan(progress[0].elapsedMs);
  });

  it("ジョブが失敗したら、backendの文言で失敗する（文言が無ければ既定の文言）", async () => {
    respond({ json: { job_id: "j" } }, { json: { status: "failed", error: "探索に失敗しました" } });
    await expect(run()).rejects.toThrow("探索に失敗しました");
    respond({ json: { job_id: "j" } }, { json: { status: "failed", error: null } });
    await expect(run()).rejects.toThrow("ルート生成に失敗しました");
  });

  it("完了なのに結果が無ければ失敗する", async () => {
    respond({ json: { job_id: "j" } }, { json: { status: "done", result: null } });
    await expect(run()).rejects.toThrow("結果を取得できませんでした");
  });

  it("問い合わせの一時的な失敗は4回続いても諦めず、成功すれば数え直す", async () => {
    const fail = { status: 503 };
    respond(
      { json: { job_id: "j" } },
      fail,
      fail,
      fail,
      fail,
      { json: { status: "running" } },
      fail,
      fail,
      fail,
      fail,
      { json: DONE },
    );
    await expect(run()).resolves.toMatchObject({ routes: [{ id: "r1" }] });
  });

  it("問い合わせが5回続けて失敗したら、最後の失敗の文言を添えて諦める", async () => {
    respond({ json: { job_id: "j" } }, { reject: new TypeError("Failed to fetch") });
    const error = await run().catch((e: Error) => e);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toMatch(
      /^ルート生成の状況確認に続けて失敗しました（.+）。時間をおいて再度お試しください。$/,
    );
    expect((error as Error).message).not.toContain("Failed to fetch");
    expect((error as Error).cause).toBeInstanceOf(Error);
    expect(polls()).toHaveLength(5);
  });

  it("backendが結果を持つ時間を過ぎても終わらなければ、時間切れで失敗する", async () => {
    respond({ json: { job_id: "j" } }, { json: { status: "running" } });
    const promise = generateRoutes(REQUEST);
    promise.catch(() => {});
    await vi.advanceTimersByTimeAsync(routeGenerateConfig.job_result_ttl_seconds * 1000 + 2000);
    await expect(promise).rejects.toThrow("タイムアウト");
  });

  it("投稿に失敗したら、問い合わせずに失敗する", async () => {
    respond({ status: 500 });
    await expect(run()).rejects.toThrow();
    expect(calls).toHaveLength(1);
  });
});
