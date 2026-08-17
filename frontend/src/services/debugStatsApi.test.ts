// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DebugStats } from "./debugStatsApi";
import { getDebugStats } from "./debugStatsApi";

function makeResponse(overrides: Partial<{ ok: boolean; status: number; json: () => Promise<unknown> }>) {
  return {
    ok: true,
    status: 200,
    json: async () => ({}),
    ...overrides,
  };
}

describe("getDebugStats", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時はJSONをそのまま返す", async () => {
    const stats: DebugStats = {
      commit: "abc1234",
      started_at: "2026-08-15T15:29:45.023449+00:00",
      engine: "openrouteservice",
      debug_mode: false,
      external: {
        "weather:open-meteo": {
          calls: 79,
          errors: 1,
          cache_hits: 75,
          cache_misses: 4,
          total_ms: 7985,
          max_ms: 2922,
          avg_ms: 101,
          cache_hit_rate: 0.949,
          error_types: { ConnectTimeout: 1 },
          last_error_type: "ConnectTimeout",
          last_error_at: "2026-08-15T15:20:00+00:00",
          last_success_at: "2026-08-15T15:29:45.023449+00:00",
          retried_calls: 3,
          retry_attempts_total: 4,
          stale_fallback_used: 1,
        },
      },
      rate_limit_rejections: {},
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse({ json: async () => stats })));

    await expect(getDebugStats()).resolves.toEqual(stats);
  });

  it("ok:falseの場合はHTTPステータスを含むエラーを投げる", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse({ ok: false, status: 500 })));

    await expect(getDebugStats()).rejects.toThrow("システム状況の取得に失敗しました[HTTP 500]");
  });

  it("jsonのparseが失敗した場合は解析失敗のエラーを投げる", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse({
          json: async () => {
            throw new Error("parse failed");
          },
        }),
      ),
    );

    await expect(getDebugStats()).rejects.toThrow("システム状況の解析に失敗しました");
  });

  it("fetch自体が失敗した場合（通信エラー）もそのままエラーを投げる", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(getDebugStats()).rejects.toThrow("Failed to fetch");
  });
});
