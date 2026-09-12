// @vitest-environment node
import { describe, expect, it } from "vitest";
import { MAX_AXIS_WEIGHT, MIN_AXIS_WEIGHT, clampBoundaryDrag } from "./routeWeightShare";

// 帯グラフの境界ドラッグ（隣り合う2軸の間だけで重みを移す）。合計が動かないことと、
// 上下限で止まることを見る。下限は0ではない——0まで下げるとその軸が「チェックOFF」に
// 化けるため、配分の調整が軸の有効/無効を兼ねてしまう。
describe("clampBoundaryDrag", () => {
  it("移した量だけ一方が増え他方が減り、2軸の合計は変わらない", () => {
    const { weightA, weightB } = clampBoundaryDrag(0.3, 0.2, 0.05);

    expect(weightA).toBeCloseTo(0.35, 2);
    expect(weightB).toBeCloseTo(0.15, 2);
    expect(weightA + weightB).toBeCloseTo(0.5, 2);
  });

  it("逆向きにも同じだけ移る", () => {
    const { weightA, weightB } = clampBoundaryDrag(0.3, 0.2, -0.05);

    expect(weightA).toBeCloseTo(0.25, 2);
    expect(weightB).toBeCloseTo(0.25, 2);
  });

  it("上限を超えて寄せられない", () => {
    const { weightA, weightB } = clampBoundaryDrag(MAX_AXIS_WEIGHT, 0.2, 0.1);

    expect(weightA).toBeCloseTo(MAX_AXIS_WEIGHT, 2);
    expect(weightB).toBeCloseTo(0.2, 2);
  });

  it("相手を下限より下へ押し下げない（無効な軸に化けさせない）", () => {
    const { weightA, weightB } = clampBoundaryDrag(0.3, MIN_AXIS_WEIGHT, 0.1);

    expect(weightB).toBeGreaterThanOrEqual(MIN_AXIS_WEIGHT);
    expect(weightA + weightB).toBeCloseTo(0.3 + MIN_AXIS_WEIGHT, 2);
  });
});
