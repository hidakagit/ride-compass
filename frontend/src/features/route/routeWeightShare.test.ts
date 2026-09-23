// @vitest-environment node
import { describe, expect, it } from "vitest";

import { clampBoundaryDrag, totalWeight } from "./routeWeightShare";

describe("totalWeight", () => {
  it("正の重みだけを足す（0以下の軸は有効でないため合計に入れない）", () => {
    expect(totalWeight({ a: 0.25, b: 0.5, c: 0, d: -0.2 })).toBeCloseTo(0.75);
    expect(totalWeight({})).toBe(0);
  });
});

describe("clampBoundaryDrag（帯の境界をドラッグして2軸の間で重みを移す）", () => {
  it("移した量だけ一方が増え、もう一方が減る（0.01刻みへ丸める）", () => {
    expect(clampBoundaryDrag(0.3, 0.3, 0.1)).toEqual({ weightA: 0.4, weightB: 0.2 });
    expect(clampBoundaryDrag(0.3, 0.3, 0.123)).toEqual({ weightA: 0.42, weightB: 0.18 });
    expect(clampBoundaryDrag(0.3, 0.3, -0.05)).toEqual({ weightA: 0.25, weightB: 0.35 });
  });

  it("どちらの軸も0.01を下回らない（0まで下げると軸が無効に化ける）", () => {
    expect(clampBoundaryDrag(0.3, 0.3, 1)).toEqual({ weightA: 0.59, weightB: 0.01 });
    expect(clampBoundaryDrag(0.3, 0.3, -1)).toEqual({ weightA: 0.01, weightB: 0.59 });
  });

  it("どちらの軸も0.6を超えない", () => {
    expect(clampBoundaryDrag(0.5, 0.5, 1)).toEqual({ weightA: 0.6, weightB: 0.4 });
    expect(clampBoundaryDrag(0.5, 0.5, -1)).toEqual({ weightA: 0.4, weightB: 0.6 });
  });

  it("2軸の合計は、どの量を動かしても変わらない", () => {
    for (const [a, b, delta] of [
      [0.33, 0.27, 0.017],
      [0.1, 0.45, -0.333],
      [0.2, 0.2, 0.5],
    ] as const) {
      const { weightA, weightB } = clampBoundaryDrag(a, b, delta);
      expect(Number((weightA + weightB).toFixed(2))).toBe(Number((a + b).toFixed(2)));
    }
  });
});
