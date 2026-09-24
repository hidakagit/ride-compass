// @vitest-environment node
import { describe, expect, it } from "vitest";

import type { WindGridPoint } from "@/types/weather";

import { gridStageFrames, jmaStageFrames, selectFrame, sourceTimeline, type FrameRule } from "./weatherSources";

const frame = (validtime: string) => ({ basetime: validtime, member: "none", validtime });
/** 格子（日本時間・オフセット無しの時刻）。 */
const grid = (times: string[]): WindGridPoint[] => [
  {
    latitude: 35,
    longitude: 139,
    times,
    wind_speed_ms: times.map(() => 1),
    wind_direction_deg: times.map(() => 0),
    precipitation_mm: times.map(() => 1),
  } as WindGridPoint,
];

describe("sourceTimeline（段を1本の時系列へつなぐ）", () => {
  it("段の順に、前の段の最後より後の時刻だけを継ぐ", () => {
    const timeline = sourceTimeline([
      jmaStageFrames(0, [frame("20260924000000"), frame("20260924010000")]),
      jmaStageFrames(1, [frame("20260924010000"), frame("20260924020000")]),
      // 日本時間 11:00 = 協定世界時 02:00（前の段の最後と同時刻）、12:00 = 03:00
      gridStageFrames(2, grid(["2026-09-24T11:00", "2026-09-24T12:00"])),
    ]);
    expect(timeline.map(({ time, ref }) => [time.toISOString(), ref.stage])).toEqual([
      ["2026-09-24T00:00:00.000Z", 0],
      ["2026-09-24T01:00:00.000Z", 0],
      ["2026-09-24T02:00:00.000Z", 1],
      ["2026-09-24T03:00:00.000Z", 2],
    ]);
    expect(timeline[3].ref).toEqual({ stage: 2, index: 1 });
  });

  it("途中の段が取れていなければ、その前の段の直後から次の段を継ぐ", () => {
    const timeline = sourceTimeline([
      jmaStageFrames(0, [frame("20260924000000")]),
      jmaStageFrames(1, []),
      gridStageFrames(2, grid(["2026-09-24T09:00", "2026-09-24T10:00"])),
    ]);
    expect(timeline.map(({ ref }) => ref.stage)).toEqual([0, 2]);
  });

  it("どの段も無ければ空", () => {
    expect(sourceTimeline([jmaStageFrames(0, []), gridStageFrames(1, [])])).toEqual([]);
  });
});

describe("gridStageFrames（格子の段のコマ）", () => {
  it("どの端末の時刻帯でも、格子の時刻は日本時間として読む", () => {
    expect(gridStageFrames(0, grid(["2026-09-24T09:00"]))[0].time.toISOString()).toBe("2026-09-24T00:00:00.000Z");
  });
});

describe("selectFrame（選んだ時刻に描くコマ）", () => {
  const now = new Date("2026-09-24T00:00:00Z");
  const minutes = (value: number) => new Date(now.getTime() + value * 60_000);
  // 0分・10分・20分の3コマ。
  const frames = [0, 10, 20].map((value) => ({ time: minutes(value), ref: value }));
  const pick = (rule: FrameRule, at: Date) => selectFrame(rule, frames, at, now)?.ref;

  it("一番近いコマ: 範囲内は最も近いコマ、範囲の外では描かない", () => {
    const rule: FrameRule = { kind: "nearest", windowMinutes: null };
    expect(pick(rule, minutes(6))).toBe(10);
    expect(pick(rule, minutes(21))).toBeUndefined();
  });

  it("最新の観測: 最新の観測から窓の幅までは最新の観測を出し、それより先では描かない", () => {
    const rule: FrameRule = { kind: "latestObservation", windowMinutes: 20 };
    expect(pick(rule, minutes(40))).toBe(20);
    expect(pick(rule, minutes(41))).toBeUndefined();
  });

  it("現在: 窓が無ければ選んだ時刻によらず現在のコマ、窓があれば現在から窓の幅の間だけ", () => {
    expect(pick({ kind: "current", windowMinutes: null }, minutes(24 * 60))).toBe(0);
    const windowed: FrameRule = { kind: "current", windowMinutes: 180 };
    expect(pick(windowed, minutes(180))).toBe(0);
    expect(pick(windowed, minutes(181))).toBeUndefined();
  });

  it("コマが無ければ、どの規則でも描かない", () => {
    expect(selectFrame({ kind: "current", windowMinutes: null }, [], now, now)).toBeUndefined();
    expect(selectFrame({ kind: "nearest", windowMinutes: null }, [], now, now)).toBeUndefined();
  });
});
