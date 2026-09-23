// @vitest-environment node
// 時刻はどれも時点（オフセット付き）で与え、期待値はテストを動かす環境の時刻帯によらない。
import { describe, expect, it } from "vitest";

import { buildDepartureFrames, buildDepartureTimeline } from "./departureTimeline";

const jst = (text: string) => new Date(`${text}+09:00`);
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

describe("buildDepartureTimeline（出発時刻を選ぶ目盛り）", () => {
  it("開いた時刻を5分刻みへ切り下げて始め、1時間以上先の最初の正時までは5分刻み", () => {
    const times = buildDepartureTimeline(jst("2026-09-24T09:07"));
    expect(times[0]).toEqual(jst("2026-09-24T09:05"));
    const fine = times.slice(0, times.findIndex((t) => t.getTime() === jst("2026-09-24T11:00").getTime()) + 1);
    expect(fine.every((t, i) => i === 0 || t.getTime() - fine[i - 1].getTime() === 5 * MINUTE)).toBe(true);
    expect(fine.at(-1)).toEqual(jst("2026-09-24T11:00"));
  });

  it("5分刻みの後は、開いた時刻の48時間後まで1時間刻み", () => {
    const anchor = jst("2026-09-24T09:07");
    const times = buildDepartureTimeline(anchor);
    const cut = times.findIndex((t) => t.getTime() === jst("2026-09-24T11:00").getTime());
    const hourly = times.slice(cut);
    expect(hourly.length).toBeGreaterThan(1);
    expect(hourly.every((t, i) => i === 0 || t.getTime() - hourly[i - 1].getTime() === HOUR)).toBe(true);
    expect(times.at(-1)).toEqual(jst("2026-09-26T09:00"));
    expect(times.at(-1)!.getTime()).toBeLessThanOrEqual(anchor.getTime() + 48 * HOUR);
  });

  it("開いた時刻の1時間後がちょうど正時なら、そこで1時間刻みへ切り替える", () => {
    const times = buildDepartureTimeline(jst("2026-09-24T09:00"));
    const i = times.findIndex((t) => t.getTime() === jst("2026-09-24T10:00").getTime());
    expect(times[i - 1]).toEqual(jst("2026-09-24T09:55"));
    expect(times[i + 1]).toEqual(jst("2026-09-24T11:00"));
  });
});

describe("buildDepartureFrames（目盛りの表記）", () => {
  const frames = buildDepartureFrames([
    jst("2026-09-24T09:55"),
    jst("2026-09-24T10:00"),
    jst("2026-09-24T11:00"),
    jst("2026-09-25T00:00"),
  ]);

  it("どの目盛りにも、日付つきの日本時間を添える", () => {
    expect(frames.map((f) => f.label)).toEqual(["9/24 09:55", "9/24 10:00", "9/24 11:00", "9/25 00:00"]);
  });

  it("正時には印を付け、日本時間の偶数時だけ時刻を書く。正時でない目盛りは分だけ", () => {
    expect(frames.map((f) => f.hourMark)).toEqual([false, true, true, true]);
    expect(frames.map((f) => f.tickLabel)).toEqual(["55", "10:00", undefined, "00:00"]);
  });
});
