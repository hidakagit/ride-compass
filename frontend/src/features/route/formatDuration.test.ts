// @vitest-environment node
import { describe, expect, it } from "vitest";

import { formatDurationShort } from "./formatDuration";

describe("formatDurationShort", () => {
  it("時間があれば「◯時間◯分」、無ければ「◯分」にする", () => {
    expect(formatDurationShort(102 * 60)).toBe("1時間42分");
    expect(formatDurationShort(60 * 60)).toBe("1時間0分");
    expect(formatDurationShort(38 * 60)).toBe("38分");
  });

  it("分へ四捨五入し、1分に満たなければ「1分未満」", () => {
    expect(formatDurationShort(29)).toBe("1分未満");
    expect(formatDurationShort(0)).toBe("1分未満");
    expect(formatDurationShort(30)).toBe("1分");
    expect(formatDurationShort(59 * 60 + 40)).toBe("1時間0分");
  });

  it("時間として読めない値は「—」", () => {
    expect(formatDurationShort(Number.NaN)).toBe("—");
    expect(formatDurationShort(Number.POSITIVE_INFINITY)).toBe("—");
    expect(formatDurationShort(-1)).toBe("—");
  });
});
