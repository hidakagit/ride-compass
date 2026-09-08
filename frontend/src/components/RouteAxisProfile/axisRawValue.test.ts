// @vitest-environment node
import { describe, expect, it } from "vitest";

import { formatAxisRawValue, totalUnitFor } from "./axisRawValue";

describe("totalUnitFor", () => {
  it("距離あたりの単位からは実数の単位が取れる", () => {
    expect(totalUnitFor("回/km")).toBe("回");
  });

  it("距離あたりでない単位はnull（距離を掛けても意味を持たない）", () => {
    expect(totalUnitFor("%")).toBeNull();
    expect(totalUnitFor("")).toBeNull();
  });
});

describe("formatAxisRawValue", () => {
  it("距離あたりの単位なら、経路全体の実数を添える", () => {
    // 0.8回/km × 32.5km ≒ 26回
    expect(formatAxisRawValue(0.8, "回/km", 32.5)).toBe("0.80回/km・約26回");
  });

  it("距離あたりでない単位は実数を添えない", () => {
    expect(formatAxisRawValue(4.2, "%", 32.5)).toBe("4.2%");
  });

  it("値の大きさに応じて桁を変える（行動が変わらない細かさは出さない）", () => {
    expect(formatAxisRawValue(15.4, "回/km", null)).toBe("15回/km");
    expect(formatAxisRawValue(3.2, "回/km", null)).toBe("3.2回/km");
    expect(formatAxisRawValue(0.08, "回/km", null)).toBe("0.08回/km");
  });

  it("実数が1回に満たなければ添えない（「約0回」は情報にならない）", () => {
    expect(formatAxisRawValue(0.01, "回/km", 20)).toBe("0.01回/km");
  });

  it("値や単位が無ければ何も出さない", () => {
    expect(formatAxisRawValue(undefined, "回/km", 20)).toBeNull();
    expect(formatAxisRawValue(0.8, null, 20)).toBeNull();
    expect(formatAxisRawValue(0.8, "", 20)).toBeNull();
  });
});
