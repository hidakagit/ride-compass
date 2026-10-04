// @vitest-environment node
/**
 * `features/route/routeWeightShare.ts`——重み配分の帯の計算。
 * - `totalWeight`: 有効な軸（重みが正）の重みの合計
 * - `clampBoundaryDrag`: 隣り合う2軸の境界を動かした量を、2軸の合計を変えずに、どちらも刻みの倍数で
 *   [刻み, 上限]に収まる2軸の新しい重みへ直す。上限は生成物（`route-generate-config.json: max_axis_weight`）が配る
 *
 * ここで見ないもの:
 * - ドラッグ・矢印キーの操作から動かした量を作ること、帯の描き方 → `RouteSettingsPanel.test.tsx`
 */
import { describe, expect, it } from "vitest";

import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import { WEIGHT_STEP, clampBoundaryDrag, totalWeight } from "./routeWeightShare";

const MAX = routeGenerateConfig.max_axis_weight;

describe("totalWeight", () => {
  it("重みが正の軸だけを足し、重み0（無効）の軸は数えない", () => {
    expect(totalWeight({ a: 0.25, b: 0, c: 0.5 })).toBeCloseTo(0.75);
  });

  it("軸が無ければ0", () => {
    expect(totalWeight({})).toBe(0);
  });
});

describe("clampBoundaryDrag", () => {
  it("動かした量だけ一方へ足し、もう一方から引く", () => {
    expect(clampBoundaryDrag(0.3, 0.3, 0.1)).toEqual({ weightA: 0.4, weightB: 0.2 });
    expect(clampBoundaryDrag(0.3, 0.3, -0.1)).toEqual({ weightA: 0.2, weightB: 0.4 });
  });

  it("動かした量は刻みの倍数へ丸める", () => {
    expect(clampBoundaryDrag(0.3, 0.3, 0.034)).toEqual({ weightA: 0.33, weightB: 0.27 });
    expect(clampBoundaryDrag(0.3, 0.3, WEIGHT_STEP * 0.4)).toEqual({ weightA: 0.3, weightB: 0.3 });
  });

  it("引かれる側は刻みで止まり、0（無効）まで下がらない", () => {
    expect(clampBoundaryDrag(0.2, 0.2, 0.5)).toEqual({ weightA: 0.39, weightB: WEIGHT_STEP });
    expect(clampBoundaryDrag(0.2, 0.2, -0.5)).toEqual({ weightA: WEIGHT_STEP, weightB: 0.39 });
  });

  it("足される側は上限で止まる", () => {
    expect(clampBoundaryDrag(MAX - 0.1, 0.5, 0.3)).toEqual({ weightA: MAX, weightB: 0.4 });
    expect(clampBoundaryDrag(0.5, MAX - 0.1, -0.3)).toEqual({ weightA: 0.4, weightB: MAX });
  });

  it("どの入力でも、2軸の合計は変わらず、どちらも刻みの倍数で[刻み, 上限]に収まる", () => {
    const starts = [WEIGHT_STEP, 0.07, 0.13, 0.3, MAX];
    const deltas = [-1, -0.123, -0.005, 0, 0.004, 0.077, 1];
    for (const a of starts) {
      for (const b of starts) {
        for (const delta of deltas) {
          const { weightA, weightB } = clampBoundaryDrag(a, b, delta);
          const label = `${a}, ${b}, ${delta}`;
          expect(weightA + weightB, label).toBeCloseTo(a + b, 10);
          for (const w of [weightA, weightB]) {
            expect(w, label).toBeGreaterThanOrEqual(WEIGHT_STEP);
            expect(w, label).toBeLessThanOrEqual(MAX);
            expect(Math.round(w / WEIGHT_STEP) * WEIGHT_STEP, label).toBeCloseTo(w, 10);
          }
        }
      }
    }
  });
});
