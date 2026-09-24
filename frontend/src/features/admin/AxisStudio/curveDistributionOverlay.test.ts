// @vitest-environment node
/**
 * `curveDistributionOverlay.ts`——曲線エディタの表示範囲へ、生値の分布の階級・分位を重ねること。範囲を
 * またぐ階級は幅に比例して按分し、範囲の外にある延長は捨てずに割合として返す。
 *
 * ここで見ないもの:
 * - 重ねたものの描画と、範囲外の割合を出すしきい値 → `BreakpointCurveEditor.test.tsx`
 */
import { describe, expect, it } from "vitest";

import { maxBarShare, offRangeShare, quantileMarkers, visibleBars } from "./curveDistributionOverlay";
import type { ValueDistribution } from "./scoreDistribution";

function distribution(bins: [number, number, number][], quantiles: Record<string, number> = {}): ValueDistribution {
  return { sample_ways: 1, total_km: 1, quantiles, bins, zero_share: 0 };
}

const sum = (values: number[]) => values.reduce((total, value) => total + value, 0);

describe("visibleBars", () => {
  it("範囲に収まる階級はそのまま、またぐ階級は範囲で切って幅に比例して按分し、外の階級は落とす", () => {
    const bars = visibleBars(
      distribution([
        [0, 10, 0.2],
        [10, 30, 0.4],
        [30, 40, 0.4],
      ]),
      0,
      20,
    );

    expect(bars).toHaveLength(2);
    expect(bars[0]).toEqual({ from: 0, to: 10, share: 0.2 });
    expect(bars[1].from).toBe(10);
    expect(bars[1].to).toBe(20);
    expect(bars[1].share).toBeCloseTo(0.2);
  });

  it("幅0の階級（値が1点に集中）は、範囲内なら端を含めてそのまま載せ、範囲外なら落とす", () => {
    const bars = visibleBars(
      distribution([
        [5, 5, 0.3],
        [20, 20, 0.3],
        [25, 25, 0.4],
      ]),
      0,
      20,
    );
    expect(bars).toEqual([
      { from: 5, to: 5, share: 0.3 },
      { from: 20, to: 20, share: 0.3 },
    ]);
  });

  it("範囲の端に接するだけの階級は載せない", () => {
    expect(visibleBars(distribution([[20, 30, 1]]), 0, 20)).toEqual([]);
  });

  it("分布が無い・範囲が潰れているときは何も載せない", () => {
    expect(visibleBars(null, 0, 10)).toEqual([]);
    expect(visibleBars(distribution([[0, 10, 1]]), 5, 5)).toEqual([]);
  });
});

describe("offRangeShare", () => {
  it("範囲の下・上にはみ出した延長を、幅に比例して数える", () => {
    const off = offRangeShare(
      distribution([
        [-10, 10, 0.4],
        [10, 20, 0.2],
        [15, 25, 0.4],
      ]),
      0,
      20,
    );
    expect(off.below).toBeCloseTo(0.2);
    expect(off.above).toBeCloseTo(0.2);
  });

  it("幅0の階級は、範囲より下なら下・上なら上に数え、範囲内なら数えない", () => {
    expect(
      offRangeShare(
        distribution([
          [-1, -1, 0.3],
          [5, 5, 0.3],
          [30, 30, 0.4],
        ]),
        0,
        20,
      ),
    ).toEqual({ below: 0.3, above: 0.4 });
  });

  it("範囲が潰れているときは、全量を範囲外として数える（範囲と同じ値は上に数える）", () => {
    const off = offRangeShare(
      distribution([
        [0, 4, 0.2],
        [5, 5, 0.3],
        [6, 9, 0.5],
      ]),
      5,
      5,
    );
    expect(off.below).toBeCloseTo(0.2);
    expect(off.above).toBeCloseTo(0.8);
  });

  it("分布が無ければ0", () => {
    expect(offRangeShare(null, 0, 10)).toEqual({ below: 0, above: 0 });
  });

  it.each([
    ["通常の範囲", 0, 20],
    ["潰れた範囲", 7, 7],
    ["全部より右の範囲", 100, 200],
  ])("%s: 範囲内に載せた割合と範囲外の割合を足すと、分布の全量に戻る", (_case, xMin, xMax) => {
    const bins: [number, number, number][] = [
      [-5, 3, 0.1],
      [3, 3, 0.15],
      [3, 12, 0.25],
      [12, 30, 0.3],
      [30, 30, 0.2],
    ];
    const d = distribution(bins);
    const off = offRangeShare(d, xMin, xMax);
    const inside = sum(visibleBars(d, xMin, xMax).map((bar) => bar.share));

    expect(inside + off.below + off.above).toBeCloseTo(sum(bins.map(([, , share]) => share)), 10);
  });
});

describe("quantileMarkers", () => {
  it("分位が届いていなければ、その線は引かない。分布が無ければ何も引かない", () => {
    expect(quantileMarkers(distribution([], { p50: 5 }), 0, 10)).toEqual([{ label: "p50", value: 5 }]);
    expect(quantileMarkers(null, 0, 10)).toEqual([]);
  });
});

describe("maxBarShare", () => {
  it("棒のうち最大の割合を返し、棒が無ければ0でない最小の値を返す（高さの正規化で0で割らない）", () => {
    expect(
      maxBarShare([
        { from: 0, to: 1, share: 0.2 },
        { from: 1, to: 2, share: 0.5 },
      ]),
    ).toBe(0.5);
    expect(maxBarShare([])).toBeGreaterThan(0);
  });
});
