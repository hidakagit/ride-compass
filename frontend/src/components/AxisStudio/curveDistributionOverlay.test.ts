// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  maxBarShare,
  offRangeShare,
  quantileMarkers,
  visibleBars,
} from "./curveDistributionOverlay";
import type { ValueDistribution } from "./scoreDistribution";

function distribution(
  bins: [number, number, number][],
  quantiles: Record<string, number> = {},
): ValueDistribution {
  return { sample_ways: 100, total_km: 10, quantiles, bins, zero_share: 0 };
}

describe("visibleBars", () => {
  it("表示範囲の外にある階級は落とす", () => {
    const d = distribution([
      [-10, -5, 0.3],
      [0, 5, 0.4],
      [20, 25, 0.3],
    ]);

    expect(visibleBars(d, 0, 10)).toEqual([{ from: 0, to: 5, share: 0.4 }]);
  });

  it("範囲をまたぐ階級は幅に比例して按分する", () => {
    // 階級[0,10)の半分だけが表示範囲[0,5)に入る → 割合も半分。
    const d = distribution([[0, 10, 0.8]]);

    expect(visibleBars(d, 0, 5)).toEqual([{ from: 0, to: 5, share: 0.4 }]);
  });

  it("またぐ階級を丸ごと入れも落としもしない（端で割合が跳ねないこと）", () => {
    const d = distribution([[0, 10, 1.0]]);

    // 範囲を少しずつ広げると、見える割合も連続的に増える。
    const shares = [2, 4, 6, 8].map((xMax) => visibleBars(d, 0, xMax)[0].share);

    shares.forEach((share, i) => expect(share).toBeCloseTo([0.2, 0.4, 0.6, 0.8][i], 10));
  });

  it("幅0の階級（値が1点に集中）はそのまま載せる", () => {
    const d = distribution([[3, 3, 0.9]]);

    expect(visibleBars(d, 0, 10)).toEqual([{ from: 3, to: 3, share: 0.9 }]);
  });

  it("分布が無い・範囲が潰れている場合は空", () => {
    expect(visibleBars(null, 0, 10)).toEqual([]);
    expect(visibleBars(distribution([[0, 1, 1]]), 5, 5)).toEqual([]);
  });
});

describe("offRangeShare", () => {
  it("表示範囲の外にある延長を上下それぞれ集計する", () => {
    const d = distribution([
      [-10, -5, 0.3],
      [0, 5, 0.4],
      [20, 25, 0.3],
    ]);

    expect(offRangeShare(d, 0, 10)).toEqual({ below: 0.3, above: 0.3 });
  });

  it("またぐ階級は按分し、見える分と足して元の割合になる", () => {
    const d = distribution([[0, 10, 1.0]]);
    const { below, above } = offRangeShare(d, 0, 4);
    const visible = visibleBars(d, 0, 4).reduce((a, b) => a + b.share, 0);

    expect(below).toBe(0);
    expect(visible + above).toBeCloseTo(1.0, 10);
  });

  it("範囲内に収まっていれば0", () => {
    expect(offRangeShare(distribution([[1, 2, 1.0]]), 0, 10)).toEqual({ below: 0, above: 0 });
    expect(offRangeShare(null, 0, 10)).toEqual({ below: 0, above: 0 });
  });
});

describe("quantileMarkers", () => {
  it("表示範囲に入る分位だけを返す", () => {
    const d = distribution([], { p10: -5, p50: 3, p90: 8, p99: 40 });

    expect(quantileMarkers(d, 0, 10)).toEqual([{ label: "p50", value: 3 }, { label: "p90", value: 8 }]);
  });

  it("p25/p75は描かない（線だらけにしない）", () => {
    const d = distribution([], { p10: 1, p25: 2, p50: 3, p75: 4, p90: 5, p99: 6 });

    expect(quantileMarkers(d, 0, 10).map((m) => m.label)).toEqual(["p10", "p50", "p90"]);
  });

  it("分位が欠けていても落ちない", () => {
    expect(quantileMarkers(distribution([], {}), 0, 10)).toEqual([]);
    expect(quantileMarkers(null, 0, 10)).toEqual([]);
  });
});

describe("maxBarShare", () => {
  it("棒が無くても0を返さない（高さの正規化で0除算になるため）", () => {
    expect(maxBarShare([])).toBeGreaterThan(0);
  });

  it("最大の割合を返す", () => {
    expect(maxBarShare([{ from: 0, to: 1, share: 0.2 }, { from: 1, to: 2, share: 0.5 }])).toBe(0.5);
  });
});

describe("表示範囲が潰れているとき", () => {
  // visibleBarsだけがxMax <= xMinで早期returnし、offRangeShareが分岐していなかった。
  // overlap(-∞, xMin)とoverlap(xMax, ∞)が同じ区間を二重に数え、合計が1を超えていた。
  const distribution = {
    sample_ways: 1,
    total_km: 1,
    quantiles: {},
    bins: [[0, 10, 1] as [number, number, number]],
    zero_share: 0,
  };

  it("範囲内の棒は出ず、範囲外の割合の合計は1を超えない", () => {
    expect(visibleBars(distribution, 8, 2)).toEqual([]);

    const { below, above } = offRangeShare(distribution, 8, 2);

    expect(below + above).toBeCloseTo(1, 10);
  });
});
