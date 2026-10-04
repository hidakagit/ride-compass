/**
 * `testing/generationJobs.ts`——ルート生成のジョブの代役。本物の口（`features/route/routeApi.ts: generateRoutes`）を
 * 通して、積んだ答えが生成の出された順に使われること・出した要求が積まれることを見る。
 *
 * ここで見ないもの: 口の問い合わせの間隔・打ち切り → `features/route/routeApi.test.ts`
 */
import { describe, expect, it } from "vitest";

import { generateRoutes } from "@/features/route/routeApi";
import { makeGenerationConditions, makeRouteCandidate } from "@/testing/routeFixtures";
import type { RouteGenerateRequest } from "@/types/route";

import { serveGenerationJobs } from "./generationJobs";

const REQUEST = { latitude: 35.68, longitude: 139.77, distance_km: 30 } as RouteGenerateRequest;
const CONDITIONS = makeGenerationConditions();

describe("serveGenerationJobs", () => {
  it("積んだ答えを生成の出された順に使い、出した要求を積む", async () => {
    const jobs = serveGenerationJobs();
    const route = makeRouteCandidate({ id: "r1" });
    jobs.respond([route], CONDITIONS, undefined);
    jobs.fail("混雑しています");

    await expect(generateRoutes(REQUEST)).resolves.toMatchObject({ routes: [route], conditions: CONDITIONS });
    await expect(generateRoutes(REQUEST)).rejects.toThrow("混雑しています");
    expect(jobs.submitted.map(({ body }) => body)).toEqual([REQUEST, REQUEST]);
  });

  it("候補0件の理由を、口が読む形で返す", async () => {
    const jobs = serveGenerationJobs();
    jobs.respond([], CONDITIONS, "見つかりませんでした");

    await expect(generateRoutes(REQUEST)).resolves.toMatchObject({
      routes: [],
      noCandidatesReason: "見つかりませんでした",
    });
  });
});
