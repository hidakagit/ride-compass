// @vitest-environment node
import { describe, expect, it } from "vitest";
import { LOAD_BAR_MAX_HEIGHT_RATIO, baselineDistanceKm, loadBarHeightRatio } from "./difficultyLoadBar";

describe("baselineDistanceKm", () => {
  it("一覧の中で最も短い距離を基準にする", () => {
    expect(baselineDistanceKm([{ distance_km: 40 }, { distance_km: 28 }, { distance_km: 55 }])).toBe(28);
  });

  it("距離を持たない候補は基準にしない", () => {
    expect(baselineDistanceKm([{ distance_km: null }, { distance_km: 32 }])).toBe(32);
    expect(baselineDistanceKm([{ distance_km: null }])).toBeNull();
    expect(baselineDistanceKm([])).toBeNull();
  });

  it("0km・非数は基準にしない（高さの割り算が壊れる）", () => {
    expect(baselineDistanceKm([{ distance_km: 0 }, { distance_km: Number.NaN }, { distance_km: 12 }])).toBe(12);
  });
});

describe("loadBarHeightRatio", () => {
  it("基準の候補は1.0、長いほど高くなる（面積が負荷になる）", () => {
    expect(loadBarHeightRatio(28, 28)).toBe(1);
    expect(loadBarHeightRatio(40, 28)).toBe(1.43);
  });

  it("上限で頭打ちにする", () => {
    expect(loadBarHeightRatio(200, 28)).toBe(LOAD_BAR_MAX_HEIGHT_RATIO);
  });

  it("基準より短い側へは伸ばさない（帯が潰れて長さが読めなくなる）", () => {
    expect(loadBarHeightRatio(10, 28)).toBe(1);
  });

  it("基準・距離が無ければ1.0（長さだけの帯に戻る）", () => {
    expect(loadBarHeightRatio(40, null)).toBe(1);
    expect(loadBarHeightRatio(null, 28)).toBe(1);
    expect(loadBarHeightRatio(undefined, 28)).toBe(1);
    expect(loadBarHeightRatio(40, 0)).toBe(1);
  });
});
