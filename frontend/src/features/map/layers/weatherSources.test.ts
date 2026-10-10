// @vitest-environment node
import { describe, expect, it } from "vitest";

import { jst } from "@/testing/jst";
import jmaExpectations from "@/types/generated/jma-expectations.json";
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

// 格子のどの時刻よりも前（何も落とさない）。
const BEFORE_GRID = new Date("2026-09-24T00:00:00+09:00");

describe("gridStageFrames（格子の段のコマ）", () => {
  const HOURS = ["2026-09-24T09:00", "2026-09-24T10:00", "2026-09-24T11:00"];

  it.each([
    ["今が属する1時間から先のコマだけを、格子の時刻の値で指す", grid(HOURS), "2026-09-24T10:59", HOURS.slice(1)],
    ["正時ちょうどはその1時間に入る", grid(HOURS), "2026-09-24T11:00", HOURS.slice(2)],
    ["先頭がまだ来ていなければ何も落とさない", grid(HOURS), "2026-09-24T08:30", HOURS],
    ["空の格子は空", [], "2026-09-24T10:00", []],
  ])("%s", (_scene, points, now, expected) => {
    const frames = gridStageFrames(0, points, jst(now));
    expect(frames.map(({ ref }) => ("time" in ref ? ref.time : ""))).toEqual(expected);
  });
});

describe("sourceTimeline（段を1本の時系列へつなぐ）", () => {
  it("段の順に、前の段の最後より後の時刻だけを継ぐ", () => {
    const timeline = sourceTimeline([
      jmaStageFrames(0, [frame("20260924000000"), frame("20260924010000")]),
      jmaStageFrames(1, [frame("20260924010000"), frame("20260924020000")]),
      // 日本時間 11:00 = 協定世界時 02:00（前の段の最後と同時刻）、12:00 = 03:00
      gridStageFrames(2, grid(["2026-09-24T11:00", "2026-09-24T12:00"]), BEFORE_GRID),
    ]);
    expect(timeline.map(({ time, ref }) => [time.toISOString(), ref.stage])).toEqual([
      ["2026-09-24T00:00:00.000Z", 0],
      ["2026-09-24T01:00:00.000Z", 0],
      ["2026-09-24T02:00:00.000Z", 1],
      ["2026-09-24T03:00:00.000Z", 2],
    ]);
  });

  it("各段が最初に描くコマはbackendの表（段が重なる・途中の段が空・全段が空等）と同じ", () => {
    const rows = jmaExpectations.stage_first_frames;
    expect(rows.length).toBeGreaterThan(0);
    for (const { scene, stages, first_frames } of rows) {
      const timeline = sourceTimeline(stages.map((frames, stage) => jmaStageFrames(stage, frames)));
      const firsts = stages.map((_, stage) => {
        const ref = timeline.find((each) => each.ref.stage === stage)?.ref;
        return ref !== undefined && "frame" in ref ? ref.frame : null;
      });
      expect(firsts, scene).toEqual(first_frames);
    }
  });
});

describe("selectFrame（選んだ時刻に描くコマ）", () => {
  const now = new Date("2026-09-24T00:00:00Z");
  const minutes = (value: number) => new Date(now.getTime() + value * 60_000);
  // 0分・10分・20分の3コマ。
  const frames = [0, 10, 20].map((value) => ({ time: minutes(value), ref: value }));
  const pick = (rule: FrameRule, at: Date) => selectFrame(rule, frames, at, now)?.ref;

  it("一番近いコマ: 最も近いコマ", () => {
    expect(pick({ kind: "nearest", windowMinutes: null }, minutes(6))).toBe(10);
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
});
