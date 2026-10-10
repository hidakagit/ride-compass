// @vitest-environment node
/**
 * `features/route/routeWeightShare.ts`——重み配分の帯の計算。
 * - `totalWeight`: 有効な軸（重みが正）の重みの合計
 * - `clampBoundaryDrag`: 隣り合う2軸の境界を動かした量を、2軸の合計を変えずに、どちらも刻みの倍数で
 *   重みが刻み以上・割合（有効な軸の重みの合計に対する比）が上限以下に収まる2軸の新しい重みへ直す。
 *   上限は生成物（`route-generate-config.json: max_axis_share`）が配る
 *
 * ここで見ないもの:
 * - ドラッグ・矢印キーの操作から動かした量を作ること、帯の描き方 → `RouteSettingsPanel.test.tsx`
 */
import { describe, expect, it } from "vitest";

import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import { WEIGHT_STEP, clampBoundaryDrag, totalWeight } from "./routeWeightShare";

const MAX_SHARE = routeGenerateConfig.max_axis_share;

describe("totalWeight", () => {
  it("重みが正の軸だけを足し、重み0（無効）の軸は数えない", () => {
    expect(totalWeight({ a: 0.25, b: 0, c: 0.5 })).toBeCloseTo(0.75);
  });
});

describe("clampBoundaryDrag", () => {
  it("動かした量を刻みの倍数へ丸めて、一方へ足し、もう一方から引く", () => {
    expect(clampBoundaryDrag(0.3, 0.3, 0.034, 1)).toEqual({ weightA: 0.33, weightB: 0.27 });
  });

  it("引かれる側は刻みで止まり、0（無効）まで下がらない", () => {
    expect(clampBoundaryDrag(0.2, 0.2, 0.5, 1)).toEqual({ weightA: 0.39, weightB: WEIGHT_STEP });
    expect(clampBoundaryDrag(0.2, 0.2, -0.5, 1)).toEqual({ weightA: WEIGHT_STEP, weightB: 0.39 });
  });

  it("足される側は、重みの値でなく合計に対する割合の上限で止まる", () => {
    // 合計 0.38（本番の既定の3軸）: 上限は 0.228 なので、刻みの内側の 0.22 で止まる。
    expect(clampBoundaryDrag(0.15, 0.15, 0.3, 0.38)).toEqual({ weightA: 0.22, weightB: 0.08 });
    expect(clampBoundaryDrag(0.15, 0.15, -0.3, 0.38)).toEqual({ weightA: 0.08, weightB: 0.22 });
    // 合計 1.5: 上限は 0.9 で、重みの値の 0.6 を越えて寄せられる。
    expect(clampBoundaryDrag(0.5, 0.6, 1, 1.5)).toEqual({ weightA: 0.9, weightB: 0.2 });
  });

  it("軸が2つだけなら、どちらも上限と1−上限の間に収まる", () => {
    expect(clampBoundaryDrag(0.5, 0.5, 1, 1)).toEqual({ weightA: MAX_SHARE, weightB: 1 - MAX_SHARE });
    expect(clampBoundaryDrag(0.5, 0.5, -1, 1)).toEqual({ weightA: 1 - MAX_SHARE, weightB: MAX_SHARE });
  });

  it("既に上限を超えている軸は、増やす向きでだけ止まり、減らす向きには動かせる", () => {
    // 合計 1 で 0.7（70%）の軸。
    expect(clampBoundaryDrag(0.7, 0.1, 0.05, 1)).toEqual({ weightA: 0.7, weightB: 0.1 });
    expect(clampBoundaryDrag(0.7, 0.1, -0.05, 1)).toEqual({ weightA: 0.65, weightB: 0.15 });
    expect(clampBoundaryDrag(0.1, 0.7, -0.05, 1)).toEqual({ weightA: 0.1, weightB: 0.7 });
    expect(clampBoundaryDrag(0.1, 0.7, 0.05, 1)).toEqual({ weightA: 0.15, weightB: 0.65 });
  });

  it("どの入力でも、2軸の合計は変わらず、どちらも刻みの倍数で、刻み以上・割合の上限以下に収まる", () => {
    const others = [0, 0.13, 0.5, 1.2];
    const starts = [WEIGHT_STEP, 0.07, 0.13, 0.3, 0.6];
    const deltas = [-1, -0.123, -0.005, 0, 0.004, 0.077, 1];
    // 始めから上限を超えている配分は除く（超えた軸が増えないことは上の別の it で見る）。
    const cases = others
      .flatMap((other) => starts.flatMap((a) => starts.map((b) => ({ a, b, total: a + b + other }))))
      .filter(({ a, b, total }) => Math.max(a, b) <= MAX_SHARE * total);
    expect(cases.length).toBeGreaterThan(0);
    for (const { a, b, total } of cases) {
      for (const delta of deltas) {
        const { weightA, weightB } = clampBoundaryDrag(a, b, delta, total);
        const label = `${a}, ${b}, ${delta}, ${total}`;
        expect(weightA + weightB, label).toBeCloseTo(a + b, 10);
        for (const w of [weightA, weightB]) {
          expect(w, label).toBeGreaterThanOrEqual(WEIGHT_STEP);
          expect(w / total, label).toBeLessThanOrEqual(MAX_SHARE + 1e-9);
          expect(Math.round(w / WEIGHT_STEP) * WEIGHT_STEP, label).toBeCloseTo(w, 10);
        }
      }
    }
  });
});
