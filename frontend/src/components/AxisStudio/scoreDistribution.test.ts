// @vitest-environment node
import { describe, expect, it } from "vitest";

import { distributionWarnings, scoreBands, scoreForValue, type ValueDistribution } from "./scoreDistribution";

const BP: [number, number][] = [
  [0, 0],
  [2, 25],
  [4, 50],
  [12, 100],
];

describe("scoreForValue", () => {
  it("折れ点の間を線形に補間する", () => {
    expect(scoreForValue(0, BP)).toBe(0);
    expect(scoreForValue(1, BP)).toBeCloseTo(12.5);
    expect(scoreForValue(2, BP)).toBe(25);
    expect(scoreForValue(3, BP)).toBeCloseTo(37.5);
  });

  it("最初の折れ点より小さい値・最後より大きい値は端の値で頭打ちになる", () => {
    expect(scoreForValue(-5, BP)).toBe(0);
    expect(scoreForValue(999, BP)).toBe(100);
  });

  it("折れ点が順不同でも並べ替えて扱う", () => {
    const shuffled: [number, number][] = [
      [4, 50],
      [0, 0],
      [2, 25],
    ];
    expect(scoreForValue(1, shuffled)).toBeCloseTo(12.5);
  });
});

function dist(bins: [number, number, number][]): ValueDistribution {
  return { sample_ways: 1, total_km: 1, quantiles: {}, bins, zero_share: 0 };
}

describe("scoreBands", () => {
  it("生値の階級を折れ点で得点帯へ振り分け、延長の割合を保つ", () => {
    const bands = scoreBands(
      dist([
        [0, 0.1, 0.5], // 中央0.05 → ほぼ0点
        [2, 2.2, 0.2], // 中央2.1 → 26-50
        [20, 21, 0.3], // 上限超え → 100点
      ]),
      BP,
    );
    const byLabel = Object.fromEntries(bands.map((b) => [b.label, b.share]));
    expect(byLabel["100点"]).toBeCloseTo(0.3);
    expect(byLabel["26-50"]).toBeCloseTo(0.2);
    expect(bands.reduce((sum, b) => sum + b.share, 0)).toBeCloseTo(1.0);
  });

  it("分布が無ければ全帯0で返す（読込中に破綻しない）", () => {
    const bands = scoreBands(null, BP);
    expect(bands).toHaveLength(6);
    expect(bands.every((b) => b.share === 0)).toBe(true);
  });
});

describe("distributionWarnings", () => {
  it("満点への張り付きが半分を超えたら警告する", () => {
    const warnings = distributionWarnings([
      { label: "0点", share: 0.05 },
      { label: "100点", share: 0.92 },
    ]);
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("92%");
  });

  it("ほとんどが0点でも警告する", () => {
    const warnings = distributionWarnings([
      { label: "0点", share: 0.95 },
      { label: "100点", share: 0.0 },
    ]);
    expect(warnings[0]).toContain("0点");
  });

  it("ほどよく散らばっていれば警告しない", () => {
    expect(
      distributionWarnings([
        { label: "0点", share: 0.6 },
        { label: "100点", share: 0.03 },
      ]),
    ).toEqual([]);
  });
});
