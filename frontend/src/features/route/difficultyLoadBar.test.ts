// @vitest-environment node
import { describe, expect, it } from "vitest";

import { baselineDistanceKm, loadBarHeightRatio } from "./difficultyLoadBar";

describe("baselineDistanceKm（高さ1.0とする距離）", () => {
  it("一覧の中で最も短い候補の距離", () => {
    expect(baselineDistanceKm([{ distance_km: 30 }, { distance_km: 12 }, { distance_km: 20 }])).toBe(12);
  });

  it("距離として使えない値（無い・非有限・0以下）の候補は数えない", () => {
    const routes = [
      { distance_km: null },
      {},
      { distance_km: Number.NaN },
      { distance_km: 0 },
      { distance_km: -3 },
      { distance_km: 25 },
    ];
    expect(baselineDistanceKm(routes)).toBe(25);
  });

  it("距離を持つ候補が無ければnull", () => {
    expect(baselineDistanceKm([])).toBeNull();
    expect(baselineDistanceKm([{ distance_km: null }])).toBeNull();
  });
});

describe("loadBarHeightRatio（帯の高さの倍率）", () => {
  it("基準に対する距離の比。基準より長い分だけ高くなり、0.01刻みに丸める", () => {
    expect(loadBarHeightRatio(15, 10)).toBe(1.5);
    expect(loadBarHeightRatio(13.337, 10)).toBe(1.33);
  });

  it("2倍で頭打ちにする", () => {
    expect(loadBarHeightRatio(50, 10)).toBe(2);
  });

  it("基準以下の距離は1.0（基準より低くはしない）", () => {
    expect(loadBarHeightRatio(10, 10)).toBe(1);
    expect(loadBarHeightRatio(5, 10)).toBe(1);
  });

  it("基準か自分の距離が無ければ1.0（帯は長さだけを表す）", () => {
    expect(loadBarHeightRatio(15, null)).toBe(1);
    expect(loadBarHeightRatio(15, 0)).toBe(1);
    expect(loadBarHeightRatio(null, 10)).toBe(1);
    expect(loadBarHeightRatio(undefined, 10)).toBe(1);
    expect(loadBarHeightRatio(Number.NaN, 10)).toBe(1);
  });
});
