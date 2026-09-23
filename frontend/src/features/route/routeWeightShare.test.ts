// @vitest-environment node
import { describe, expect, it } from "vitest";
import { clampBoundaryDrag } from "./routeWeightShare";

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
    // 上限の値は借りない。**上限に居るときは、そこから先へ動かない**ことだけを見る。
    const atLimit = clampBoundaryDrag(0.6, 0.2, 0);
    const pushed = clampBoundaryDrag(0.6, 0.2, 0.1);

    expect(pushed.weightA).toBeCloseTo(atLimit.weightA, 2);
    expect(pushed.weightB).toBeCloseTo(0.2, 2);
  });

  it("相手を下限より下へ押し下げない（無効な軸に化けさせない）", () => {
    // 押す量を増やしても、相手はそれ以上減らない。合計は常に保たれる。
    const pushed = clampBoundaryDrag(0.3, 0.05, 0.1);
    const pushedHarder = clampBoundaryDrag(0.3, 0.05, 0.5);

    expect(pushedHarder.weightB).toBeCloseTo(pushed.weightB, 2);
    expect(pushedHarder.weightB).toBeGreaterThan(0);
    expect(pushedHarder.weightA + pushedHarder.weightB).toBeCloseTo(0.35, 2);
  });
});
