// @vitest-environment node
/**
 * `features/route/routeApi.ts: generateRoutes`——生成のジョブをbackendへ出し、終わるまで状態を問い合わせて結果を返す口。
 * - 出した直後に1回目を問い合わせ、2回目からは間をおく。待ち・実行中の間は経過時間とともに知らせる
 * - 終われば候補・条件・候補0件の理由を返し、失敗ならbackendの文言で投げる
 * - 問い合わせの失敗は続けて決まった回数まで取り直し（成功すれば数え直す）、超えたら最後の失敗の文言を添えて投げる
 * - 結果をbackendが持つ時間（生成物`route-generate-config.json: job_result_ttl_seconds`）を過ぎたら諦める
 *
 * ここで見ないもの:
 * - 失敗の文言の組み立て・通信の失敗とタイムアウトの包み直し → `lib/apiClient.test.ts`
 * - 送る値を組み立てること・結果と進み方を画面の状態にすること → `generationRequest.test.ts`・`useRouteGeneration.test.ts`
 *
 * 差し替えたもの: 網（`fetch`）と時計（`setTimeout`・`performance`）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { stubBackend, type SentRequest } from "@/testing/backendFetch";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { GenerationConditions, RouteGenerateRequest } from "@/types/route";

import { generateRoutes } from "./routeApi";

const REQUEST: RouteGenerateRequest = {
  latitude: 35.68,
  longitude: 139.77,
  distance_km: 40,
  distance_tolerance_km: 5,
  route_type: "loop",
  hard_filters: {},
  max_routes: 3,
  assumed_speed_kmh: 22,
  start_time: "2026-10-04T01:30:00.000Z",
};
const CONDITIONS = { latitude: 35.68, longitude: 139.77, distance_km: 40 } as GenerationConditions;
const JOB_PATH = "/api/routes/generate/job-1";
const TTL_MS = routeGenerateConfig.job_result_ttl_seconds * 1000;

type Poll = Response | Error;

/** 生成の受け付けにはjob-1を返し、問い合わせには`polls`を順に返す（尽きたら最後のものを返し続ける）。 */
function stubJob(polls: Poll[]): SentRequest[] {
  let next = 0;
  return stubBackend((request) => {
    if (request.method === "POST") return Response.json({ job_id: "job-1" });
    const reply = polls[Math.min(next, polls.length - 1)];
    next += 1;
    return reply instanceof Error ? reply : reply.clone();
  });
}

const pending = (status: "queued" | "running") => Response.json({ status });
const done = (routes = [makeRouteCandidate({ id: "r1" })], noCandidatesReason: string | null = null) =>
  Response.json({
    status: "done",
    result: { routes, conditions: CONDITIONS, no_candidates_reason: noCandidatesReason },
  });

const polled = (sent: SentRequest[]) => sent.filter((request) => request.path === JOB_PATH).length;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("generateRoutes", () => {
  it("生成をPOSTで出し、そのジョブの状態をGETで問い合わせて、終われば候補と条件を返す", async () => {
    const routes = [makeRouteCandidate({ id: "r1" }), makeRouteCandidate({ id: "r2" })];
    const sent = stubJob([done(routes)]);

    await expect(generateRoutes(REQUEST)).resolves.toEqual({
      routes,
      conditions: CONDITIONS,
      noCandidatesReason: undefined,
    });
    expect(sent).toEqual([
      { method: "POST", path: "/api/routes/generate", query: {}, body: REQUEST },
      { method: "GET", path: JOB_PATH, query: {}, body: undefined },
    ]);
  });

  it("候補が0件なら、backendが返した理由を添えて返す", async () => {
    stubJob([done([], "距離の条件に合う周回が見つかりませんでした")]);

    await expect(generateRoutes(REQUEST)).resolves.toEqual({
      routes: [],
      conditions: CONDITIONS,
      noCandidatesReason: "距離の条件に合う周回が見つかりませんでした",
    });
  });

  it("1回目は出した直後に問い合わせ、2回目からは間をおき、待ち・実行中の間は経過時間とともに知らせる", async () => {
    const sent = stubJob([pending("queued"), pending("running"), done()]);
    const onProgress = vi.fn();
    const result = generateRoutes(REQUEST, onProgress);

    await vi.advanceTimersByTimeAsync(0);
    expect(polled(sent)).toBe(1);
    expect(onProgress).toHaveBeenLastCalledWith({ status: "queued", elapsedMs: 0 });

    await vi.advanceTimersByTimeAsync(1499);
    expect(polled(sent)).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(polled(sent)).toBe(2);
    expect(onProgress).toHaveBeenLastCalledWith({ status: "running", elapsedMs: 1500 });

    await vi.advanceTimersByTimeAsync(1500);
    await expect(result).resolves.toMatchObject({ routes: [expect.objectContaining({ id: "r1" })] });
    expect(onProgress).toHaveBeenCalledTimes(2);
  });

  it("ジョブが失敗したら、backendの文言で投げる", async () => {
    stubJob([Response.json({ status: "failed", error: "ルートの生成に失敗しました" })]);

    await expect(generateRoutes(REQUEST)).rejects.toThrow("ルートの生成に失敗しました");
  });

  it("生成を受け付けてもらえなければ、問い合わせずに投げる", async () => {
    const sent = stubBackend(() => Response.json({ detail: "混雑しています" }, { status: 429 }));

    await expect(generateRoutes(REQUEST)).rejects.toThrow("混雑しています");
    expect(sent).toHaveLength(1);
  });

  it("問い合わせの失敗は取り直し、途中で成功すれば失敗の数を数え直す", async () => {
    const failure = () => new Response(null, { status: 503 });
    const sent = stubJob([
      failure(),
      failure(),
      failure(),
      failure(),
      pending("running"),
      failure(),
      failure(),
      failure(),
      failure(),
      done(),
    ]);
    const result = generateRoutes(REQUEST);

    await vi.advanceTimersByTimeAsync(1500 * 9);
    await expect(result).resolves.toMatchObject({ routes: [expect.objectContaining({ id: "r1" })] });
    expect(polled(sent)).toBe(10);
  });

  it("問い合わせに5回続けて失敗したら、最後の失敗の文言を句点を重ねずに添えて投げる", async () => {
    const sent = stubJob([
      new Response(null, { status: 503 }),
      new Response(null, { status: 503 }),
      new Response(null, { status: 503 }),
      new Response(null, { status: 503 }),
      Response.json({ detail: "混雑しています。" }, { status: 503 }),
    ]);
    const result = generateRoutes(REQUEST);
    const rejected = expect(result).rejects.toThrow(
      "ルート生成の状況確認に続けて失敗しました: 混雑しています。時間をおいて再度お試しください。",
    );

    await vi.advanceTimersByTimeAsync(1500 * 4);
    await rejected;
    expect(polled(sent)).toBe(5);
  });

  it("結果をbackendが持つ時間を過ぎても終わらなければ、諦めて投げる", async () => {
    stubJob([pending("running")]);
    const result = generateRoutes(REQUEST);
    let settled = false;
    const rejected = expect(result.finally(() => (settled = true))).rejects.toThrow("ルート生成がタイムアウトしました");

    await vi.advanceTimersByTimeAsync(TTL_MS);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1500);
    await rejected;
  });
});
