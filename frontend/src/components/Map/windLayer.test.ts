import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchWindFrames, formatWindFrameTime, nearestFrameIndexToNow, windVectorSourceUrl } from "./windLayer";

describe("windLayer", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  describe("fetchWindFrames", () => {
    it("valid_timesをindex付きのフレーム配列へ変換する", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          reference_time: "2026-08-20T00:00:00Z",
          valid_times: ["2026-08-20T00:00Z", "2026-08-20T01:00Z", "2026-08-20T02:00Z"],
        }),
      }) as unknown as typeof fetch;

      const frames = await fetchWindFrames();
      expect(frames).toEqual([
        { validTime: "2026-08-20T00:00Z", index: 0 },
        { validTime: "2026-08-20T01:00Z", index: 1 },
        { validTime: "2026-08-20T02:00Z", index: 2 },
      ]);
    });

    it("HTTPエラー時は例外を投げる", async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 503 }) as unknown as typeof fetch;
      await expect(fetchWindFrames()).rejects.toThrow("503");
    });

    it("valid_timesが空配列の応答は例外を投げる", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ reference_time: "2026-08-20T00:00:00Z", valid_times: [] }),
      }) as unknown as typeof fetch;
      await expect(fetchWindFrames()).rejects.toThrow();
    });

    it("valid_timesが無い想定外の形式は例外を投げる", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ reference_time: "2026-08-20T00:00:00Z" }),
      }) as unknown as typeof fetch;
      await expect(fetchWindFrames()).rejects.toThrow();
    });
  });

  describe("nearestFrameIndexToNow", () => {
    const frames = [
      { validTime: "2026-08-20T00:00Z", index: 0 },
      { validTime: "2026-08-20T03:00Z", index: 1 },
      { validTime: "2026-08-20T06:00Z", index: 2 },
    ];

    it("現在時刻に最も近いフレームのindexを返す", () => {
      expect(nearestFrameIndexToNow(frames, new Date("2026-08-20T04:40:00Z"))).toBe(2);
      expect(nearestFrameIndexToNow(frames, new Date("2026-08-20T01:00:00Z"))).toBe(0);
    });

    it("空配列なら0を返す", () => {
      expect(nearestFrameIndexToNow([], new Date())).toBe(0);
    });
  });

  describe("windVectorSourceUrl", () => {
    it("om://プロトコル・time_step・variable・arrows=trueを含むURLを組み立てる", () => {
      const url = windVectorSourceUrl({ validTime: "2026-08-20T03:00Z", index: 7 });
      expect(url).toBe(
        "om://https://openmeteo-data-spatial.b-cdn.net/jma_msm/latest.json?time_step=valid_times_7&variable=wind_u_component_10m&arrows=true"
      );
    });
  });

  describe("formatWindFrameTime", () => {
    it("UTC時刻をJSTの日付・時刻表示へ変換する", () => {
      // 2026-08-20T03:00Z = JST 12:00
      expect(formatWindFrameTime("2026-08-20T03:00Z")).toBe("8/20 12:00");
    });

    it("日付をまたぐ時刻も正しく変換する", () => {
      // 2026-08-20T21:00Z = JST 8/21 06:00
      expect(formatWindFrameTime("2026-08-20T21:00Z")).toBe("8/21 06:00");
    });
  });
});
