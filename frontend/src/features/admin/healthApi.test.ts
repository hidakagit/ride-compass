// @vitest-environment node
/**
 * `healthApi.ts`——backendへ疎通できるかを、例外にせず真偽で返すこと。
 *
 * ここで見ないもの:
 * - 叩く先がbackendの契約にあること → `adminApiClients.test.ts`
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { checkBackendHealth } from "./healthApi";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(impl: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

describe("checkBackendHealth", () => {
  it("backendが status: ok を返したときだけ真", async () => {
    stubFetch(async () => new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
    await expect(checkBackendHealth()).resolves.toBe(true);
  });

  it("応答はあるが status が ok でなければ偽", async () => {
    stubFetch(async () => new Response(JSON.stringify({ status: "degraded" }), { status: 200 }));
    await expect(checkBackendHealth()).resolves.toBe(false);
  });

  it("通信そのものの失敗も偽（例外にしない）", async () => {
    stubFetch(async () => {
      throw new TypeError("fetch failed");
    });
    await expect(checkBackendHealth()).resolves.toBe(false);
  });
});
