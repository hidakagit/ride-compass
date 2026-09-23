// @vitest-environment node
// 期待値はどれも、テストを動かす環境の時刻帯によらない（日本時間で書く、が実装の決めていること）。
import { describe, expect, it } from "vitest";

import {
  formatJstDateTime,
  formatJstHourMinute,
  formatJstMinute,
  fromJstDatetimeLocalValue,
  isSameJstDay,
  jstParts,
  nearestTimeIndex,
  toJstDatetimeLocalValue,
} from "./time";

// 協定世界時では前日の15:30、日本時間では当日の0:30。
const JUST_AFTER_JST_MIDNIGHT = new Date("2026-09-23T15:30:00Z");

describe("日本時間の暦と時刻", () => {
  it("協定世界時から9時間進めた暦と時刻（日付をまたぐ）", () => {
    expect(jstParts(JUST_AFTER_JST_MIDNIGHT)).toEqual({ year: 2026, month: 9, day: 24, hour: 0, minute: 30 });
  });

  it("書式: 時:分は2桁ずつ、月/日は0埋めしない、分だけは2桁", () => {
    expect(formatJstHourMinute(JUST_AFTER_JST_MIDNIGHT)).toBe("00:30");
    expect(formatJstDateTime(JUST_AFTER_JST_MIDNIGHT)).toBe("9/24 00:30");
    expect(formatJstMinute(new Date("2026-09-24T09:05:00+09:00"))).toBe("05");
  });

  it("同じ日かは日本時間の日付で決める", () => {
    const lateNightUtc = new Date("2026-09-23T23:00:00Z"); // 日本時間 9/24 8:00
    expect(isSameJstDay(JUST_AFTER_JST_MIDNIGHT, lateNightUtc)).toBe(true);
    expect(isSameJstDay(new Date("2026-09-24T23:59:00+09:00"), new Date("2026-09-25T00:00:00+09:00"))).toBe(false);
  });
});

describe("日時の入力欄（datetime-local）の値", () => {
  it("日本時間の YYYY-MM-DDTHH:mm で書き、同じ時点へ読み戻す", () => {
    expect(toJstDatetimeLocalValue(JUST_AFTER_JST_MIDNIGHT)).toBe("2026-09-24T00:30");
    expect(fromJstDatetimeLocalValue("2026-09-24T00:30").getTime()).toBe(JUST_AFTER_JST_MIDNIGHT.getTime());
  });

  it("読めない値は無効な時点になる（呼び出し側が捨てる）", () => {
    expect(Number.isNaN(fromJstDatetimeLocalValue("").getTime())).toBe(true);
  });
});

describe("nearestTimeIndex（最も近いコマ）", () => {
  const times = [0, 10, 20].map((minute) => new Date(Date.UTC(2026, 8, 24, 0, minute)));
  const at = (minute: number) => new Date(Date.UTC(2026, 8, 24, 0, minute));

  it("最も近い時点の位置。同じだけ離れていれば先の方", () => {
    expect(nearestTimeIndex(times, at(12))).toBe(1);
    expect(nearestTimeIndex(times, at(15))).toBe(1);
  });

  it("範囲の外は端へ寄せ、空なら0", () => {
    expect(nearestTimeIndex(times, at(-30))).toBe(0);
    expect(nearestTimeIndex(times, at(90))).toBe(2);
    expect(nearestTimeIndex([], at(0))).toBe(0);
  });
});
