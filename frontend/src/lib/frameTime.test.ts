// @vitest-environment node
import { describe, expect, it } from "vitest";
import { formatDynamicFrameTime, nearestTimeIndex } from "./frameTime";

describe("frameTime", () => {
  describe("formatDynamicFrameTime", () => {
    it("JSTで月/日 時:分の形式にする", () => {
      expect(formatDynamicFrameTime(new Date("2026-08-20T12:05:00+09:00"))).toBe("8/20 12:05");
    });

    it("日付をまたぐ時刻も正しく変換する", () => {
      expect(formatDynamicFrameTime(new Date("2026-08-21T06:00:00+09:00"))).toBe("8/21 06:00");
    });
  });

  describe("nearestTimeIndex", () => {
    const times = [
      new Date("2026-08-20T00:00:00+09:00"),
      new Date("2026-08-20T03:00:00+09:00"),
      new Date("2026-08-20T06:00:00+09:00"),
    ];

    it("対象時刻に最も近いindexを返す", () => {
      expect(nearestTimeIndex(times, new Date("2026-08-20T04:40:00+09:00"))).toBe(2);
      expect(nearestTimeIndex(times, new Date("2026-08-20T01:00:00+09:00"))).toBe(0);
    });

    it("空配列なら0を返す", () => {
      expect(nearestTimeIndex([], new Date())).toBe(0);
    });
  });
});
