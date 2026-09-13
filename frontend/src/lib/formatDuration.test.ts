// @vitest-environment node
import { describe, expect, it } from "vitest";
import { formatDurationShort } from "./formatDuration";

describe("formatDurationShort", () => {
  it("1時間以上は時間と分に分ける", () => {
    expect(formatDurationShort(6120)).toBe("1時間42分");
    expect(formatDurationShort(3600)).toBe("1時間0分");
  });

  it("1時間未満は分だけにする", () => {
    expect(formatDurationShort(2280)).toBe("38分");
  });

  it("1分未満と不正な値を区別する", () => {
    expect(formatDurationShort(20)).toBe("1分未満");
    expect(formatDurationShort(-1)).toBe("—");
    expect(formatDurationShort(Number.NaN)).toBe("—");
  });
});
