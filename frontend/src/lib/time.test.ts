// @vitest-environment node
/**
 * `lib/time.ts`——画面に出す時刻を、見る人の端末の時刻帯によらず日本時間で扱う。
 *
 * 時点は協定世界時（末尾`Z`）で書いて与える。開発機（日本時間）とCI（協定世界時）のどちらでも同じ答えになることが、
 * 端末の時刻帯によらないという約束そのもの。
 *
 * ここで見ないもの:
 * - 時刻の一覧をどう作り、どのコマを見せるか → 使う側（`features/map/layers/dynamicWeather.test.ts`・
 *   `features/conditions/RideConditionBar`）
 */
import { describe, expect, it } from "vitest";

import {
  formatJstDateTime,
  formatJstHourMinute,
  formatJstMinute,
  isSameJstDay,
  jstParts,
  nearestTimeIndex,
  parseJstLocalValue,
  toJstLocalValue,
} from "@/lib/time";

const at = (iso: string) => new Date(iso);

describe("jstParts", () => {
  it("協定世界時から9時間進めた暦と時刻を返す（月は1から数える）", () => {
    expect(jstParts(at("2026-08-20T00:05:00Z"))).toEqual({ year: 2026, month: 8, day: 20, hour: 9, minute: 5 });
  });

  it("協定世界時の15時からは日本時間の翌日になり、年末なら年と月も進む", () => {
    expect(jstParts(at("2026-12-31T15:00:00Z"))).toEqual({ year: 2027, month: 1, day: 1, hour: 0, minute: 0 });
  });
});

describe("書式", () => {
  const time = at("2026-08-20T00:05:00Z");

  it("時刻は時と分を2桁にする", () => {
    expect(formatJstHourMinute(time)).toBe("09:05");
  });

  it("日時は月と日を詰め、時刻を2桁にする", () => {
    expect(formatJstDateTime(time)).toBe("8/20 09:05");
  });

  it("分だけを2桁で出す", () => {
    expect(formatJstMinute(time)).toBe("05");
  });
});

describe("isSameJstDay", () => {
  it("協定世界時では別の日でも、日本時間で同じ日なら同じ日とする", () => {
    expect(isSameJstDay(at("2026-08-19T15:00:00Z"), at("2026-08-20T14:59:00Z"))).toBe(true);
  });

  it("協定世界時では同じ日でも、日本時間で日をまたげば別の日とする", () => {
    expect(isSameJstDay(at("2026-08-20T14:59:00Z"), at("2026-08-20T15:00:00Z"))).toBe(false);
  });

  it.each([
    ["年だけが違う", "2027-08-20T00:00:00Z"],
    ["月だけが違う", "2026-09-20T00:00:00Z"],
  ])("日付の数字が同じでも、%sなら別の日とする", (_scene, other) => {
    expect(isSameJstDay(at("2026-08-20T00:00:00Z"), at(other))).toBe(false);
  });
});

describe("日時の入力欄の値（時刻帯を持たない`YYYY-MM-DDTHH:mm`）", () => {
  it("日本時間の暦と時刻を、各項目を2桁にして書く", () => {
    expect(toJstLocalValue(at("2026-01-02T00:05:00Z"))).toBe("2026-01-02T09:05");
  });

  it("日本時間として読む", () => {
    expect(parseJstLocalValue("2026-01-02T09:05").toISOString()).toBe("2026-01-02T00:05:00.000Z");
  });

  it("書いた値を読むと、分の単位で元の時点に戻る", () => {
    const time = at("2026-12-31T15:30:00Z");

    expect(parseJstLocalValue(toJstLocalValue(time)).getTime()).toBe(time.getTime());
  });
});

describe("nearestTimeIndex", () => {
  const times = ["2026-08-20T00:00:00Z", "2026-08-20T01:00:00Z", "2026-08-20T02:00:00Z"].map(at);

  it("一覧が空なら、先頭（0）を返す", () => {
    expect(nearestTimeIndex([], at("2026-08-20T00:00:00Z"))).toBe(0);
  });

  it("最も近い時刻の位置を返す", () => {
    expect(nearestTimeIndex(times, at("2026-08-20T01:20:00Z"))).toBe(1);
    expect(nearestTimeIndex(times, at("2026-08-20T01:40:00Z"))).toBe(2);
  });

  it("2つの時刻からちょうど同じだけ離れていれば、前の時刻を選ぶ", () => {
    expect(nearestTimeIndex(times, at("2026-08-20T01:30:00Z"))).toBe(1);
  });

  it("一覧の範囲の外は、近い側の端へ寄せる", () => {
    expect(nearestTimeIndex(times, at("2026-08-19T00:00:00Z"))).toBe(0);
    expect(nearestTimeIndex(times, at("2026-08-21T00:00:00Z"))).toBe(2);
  });
});
