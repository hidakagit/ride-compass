// @vitest-environment node
import { describe, expect, it } from "vitest";
import { buildDepartureFrames, buildDepartureTimeline } from "./departureTimeline";

describe("buildDepartureTimeline", () => {
  it("直近60分は5分刻み、以降は1時間刻みで48時間先まで並ぶ", () => {
    const anchor = new Date("2026-09-05T09:03:00+09:00");
    const timeline = buildDepartureTimeline(anchor);

    expect(timeline[0].toISOString()).toBe(new Date("2026-09-05T09:00:00+09:00").toISOString());
    expect(timeline[1].toISOString()).toBe(new Date("2026-09-05T09:05:00+09:00").toISOString());

    const fineCount = 60 / 5 + 1;
    expect(timeline[fineCount - 1].toISOString()).toBe(new Date("2026-09-05T10:00:00+09:00").toISOString());
    expect(timeline[fineCount].toISOString()).toBe(new Date("2026-09-05T11:00:00+09:00").toISOString());

    const last = timeline[timeline.length - 1];
    expect(last.getTime()).toBeGreaterThanOrEqual(anchor.getTime() + 47 * 60 * 60_000);
    expect(last.getTime()).toBeLessThanOrEqual(anchor.getTime() + 48 * 60 * 60_000);
  });

  it("昇順かつ重複なし", () => {
    const timeline = buildDepartureTimeline(new Date("2026-09-05T23:58:00+09:00"));
    for (let i = 1; i < timeline.length; i++) {
      expect(timeline[i].getTime()).toBeGreaterThan(timeline[i - 1].getTime());
    }
  });
});

describe("buildDepartureFrames", () => {
  it("正時はhourMarkを立てて2時間おきにtickLabelを出す、それ以外は分のみ", () => {
    const timeline = [
      new Date("2026-09-05T09:00:00+09:00"),
      new Date("2026-09-05T09:05:00+09:00"),
      new Date("2026-09-05T10:00:00+09:00"),
      new Date("2026-09-05T11:00:00+09:00"),
    ];
    const frames = buildDepartureFrames(timeline);

    expect(frames[0]).toMatchObject({ hourMark: true, tickLabel: "09:00" });
    expect(frames[1]).toMatchObject({ hourMark: false, tickLabel: "05" });
    expect(frames[2]).toMatchObject({ hourMark: true, tickLabel: undefined });
    expect(frames[3]).toMatchObject({ hourMark: true, tickLabel: "11:00" });
  });
});
