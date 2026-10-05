// @vitest-environment node
/**
 * `features/route/formatDuration.ts: formatDurationShort`——秒を分の表記にする。1時間を超えても分で書き、
 * 1分に満たないものは「1分未満」、数として読めない秒は「—」にする。
 *
 * ここで見ないもの:
 * - どの所要時間をどこに出すか → 使う部品（候補の一覧・候補の中身・乗り換えの比較）のテスト
 */
import { describe, expect, it } from "vitest";

import { formatDurationShort } from "./formatDuration";

describe("formatDurationShort", () => {
  it("丸めて1分に満たないものは「1分未満」、半分ちょうどからは「1分」", () => {
    expect(formatDurationShort(29)).toBe("1分未満");
    expect(formatDurationShort(30)).toBe("1分");
  });

  it.each([
    ["負の秒", -1],
    ["NaN", Number.NaN],
  ])("%sは「—」", (_label, seconds) => {
    expect(formatDurationShort(seconds)).toBe("—");
  });
});
