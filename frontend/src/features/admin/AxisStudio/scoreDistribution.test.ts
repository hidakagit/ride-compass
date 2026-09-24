// @vitest-environment node
/**
 * `scoreDistribution.ts`——生値の分布へ折れ点を当てはめ、得点帯ごとの延長割合を出し、満点への張り付きと
 * 0点への偏りを警告すること。
 *
 * 帯の名前は判定と同じ並びから作られる。期待値は帯の名前（「1-25」「100点」）が表す範囲から引き、
 * 境界の値を書き写さない。
 *
 * ここで見ないもの:
 * - 折れ点での補間そのもの → `breakpointTools.test.ts`
 * - 帯と警告を画面にどう出すか → `DistributionPreview.test.tsx`
 */
import { describe, expect, it } from "vitest";

import { distributionWarnings, scoreBands, type ValueDistribution } from "./scoreDistribution";

const IDENTITY: [number, number][] = [
  [0, 0],
  [100, 100],
];

function distribution(bins: [number, number, number][]): ValueDistribution {
  return { sample_ways: 1, total_km: 1, quantiles: {}, bins, zero_share: 0 };
}

/** 「0点」「1-25」「100点」を、その帯が受け持つ点数の範囲へ読む。 */
function rangeOf(label: string): [number, number] {
  const single = /^(\d+)点$/.exec(label);
  if (single) return [Number(single[1]), Number(single[1])];
  const [low, high] = label.split("-").map(Number);
  return [low, high];
}

describe("scoreBands", () => {
  it("分布が無い・階級が無いときも、全帯を0で返す", () => {
    for (const empty of [null, distribution([])]) {
      const bands = scoreBands(empty, IDENTITY);
      expect(bands.length).toBeGreaterThan(0);
      expect(bands.every((band) => band.share === 0)).toBe(true);
    }
  });

  it("0点と100点は単独の帯で、帯は0点から100点まで隙間なく並ぶ", () => {
    const labels = scoreBands(null, IDENTITY).map((band) => band.label);
    expect(rangeOf(labels[0])).toEqual([0, 0]);
    expect(rangeOf(labels.at(-1)!)).toEqual([100, 100]);
    for (let i = 1; i < labels.length; i++) {
      expect(rangeOf(labels[i])[0]).toBe(rangeOf(labels[i - 1])[1] + 1);
    }
  });

  it("0〜100の整数の点数は、その点数を名前の範囲に含む帯へ入る", () => {
    const labels = scoreBands(null, IDENTITY).map((band) => band.label);
    for (let score = 0; score <= 100; score++) {
      const bands = scoreBands(distribution([[score, score, 1]]), IDENTITY);
      const hit = bands.findIndex((band) => band.share === 1);
      const [low, high] = rangeOf(labels[hit]);
      expect(score, `点数${score}が帯「${labels[hit]}」へ入った`).toBeGreaterThanOrEqual(low);
      expect(score).toBeLessThanOrEqual(high);
    }
  });

  it("99点台の端数は、100点ではなく一つ手前の帯へ入る", () => {
    const bands = scoreBands(distribution([[99.5, 99.5, 1]]), IDENTITY);
    expect(bands.at(-1)!.share).toBe(0);
    expect(bands.at(-2)!.share).toBe(1);
  });

  it("階級は中央の値で点数を決め、同じ帯に入った階級の割合は足し合わせる", () => {
    const steep: [number, number][] = [
      [0, 0],
      [10, 100],
    ];
    const bands = scoreBands(
      distribution([
        [0, 2, 0.3],
        [8, 12, 0.2],
        [20, 30, 0.5],
      ]),
      steep,
    );

    expect(bands[1].share).toBeCloseTo(0.3);
    expect(bands.at(-1)!.share).toBeCloseTo(0.7);
  });
});

describe("distributionWarnings", () => {
  function bandsWith(zero: number, full: number) {
    return scoreBands(
      distribution([
        [-1, -1, zero],
        [200, 200, full],
        [50, 50, 1 - zero - full],
      ]),
      IDENTITY,
    );
  }

  it("満点が延長の半分以上なら、その割合で張り付きを警告する", () => {
    expect(distributionWarnings(bandsWith(0, 0.5))).toEqual([expect.stringContaining("50%が満点に張り付きます")]);
    expect(distributionWarnings(bandsWith(0, 0.49))).toEqual([]);
  });

  it("0点が延長の9割以上なら、その割合で偏りを警告する", () => {
    expect(distributionWarnings(bandsWith(0.9, 0))).toEqual([expect.stringContaining("90%が0点です")]);
    expect(distributionWarnings(bandsWith(0.89, 0))).toEqual([]);
  });

  it("警告の割合は整数の百分率へ丸める", () => {
    expect(distributionWarnings(bandsWith(0, 0.666))).toEqual([expect.stringContaining("67%")]);
  });
});
