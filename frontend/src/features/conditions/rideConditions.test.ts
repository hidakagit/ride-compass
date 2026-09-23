// @vitest-environment node
// 時刻はどれも時点（オフセット付き）で与え、期待値はテストを動かす環境の時刻帯によらない。
import { describe, expect, it } from "vitest";

import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import { clampSpeedKmh, formatDepartureLabel } from "./rideConditions";

describe("formatDepartureLabel（出発時刻の表示）", () => {
  const now = new Date("2026-09-24T12:00:00+09:00");

  it("今日なら時:分（時は0埋めしない）、別の日なら月/日を前に付ける（日本時間）", () => {
    expect(formatDepartureLabel(new Date("2026-09-24T09:05:00+09:00"), now)).toBe("9:05");
    expect(formatDepartureLabel(new Date("2026-09-25T09:05:00+09:00"), now)).toBe("9/25 9:05");
  });

  it("同じ日かは日本時間の日付で決める（協定世界時で同じ日でも、日本時間で別の日なら日付を付ける）", () => {
    const justAfterJstMidnight = new Date("2026-09-24T15:30:00Z");
    expect(formatDepartureLabel(new Date("2026-09-24T14:00:00Z"), justAfterJstMidnight)).toBe("9/24 23:00");
  });
});

describe("clampSpeedKmh（想定速度）", () => {
  const { min_assumed_speed_kmh: min, max_assumed_speed_kmh: max } = routeGenerateConfig;

  it("整数へ丸め、backendが受け付ける範囲へ収める", () => {
    expect(clampSpeedKmh(min + 2.6)).toBe(min + 3);
    expect(clampSpeedKmh(min - 5)).toBe(min);
    expect(clampSpeedKmh(max + 5)).toBe(max);
  });

  it("数として読めなければ既定の速度", () => {
    expect(clampSpeedKmh(Number.NaN)).toBe(routeGenerateConfig.default_assumed_speed_kmh);
  });
});
