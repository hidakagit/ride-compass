// @vitest-environment node
import { describe, expect, it } from "vitest";
import { MAX_AXIS_WEIGHT, MIN_AXIS_WEIGHT, adjustAxisShare, totalWeight } from "./routeWeightShare";

describe("adjustAxisShare", () => {
  it("増やしたぶんを他の有効な軸から今の比率で減らし、合計は変わらない", () => {
    const before = { a: 0.25, b: 0.5, c: 0.25 };
    const after = adjustAxisShare(before, "a", 10)!;

    expect(after.a).toBeGreaterThan(before.a);
    expect(after.b).toBeLessThan(before.b);
    expect(after.c).toBeLessThan(before.c);
    // 残った軸どうしの比（b:c=2:1）は動かない＝比率どおりに按分している
    // （0.01刻みへの丸めぶんだけずれるため幅で見る）。
    const ratio = after.b / after.c;
    expect(ratio).toBeGreaterThan(1.8);
    expect(ratio).toBeLessThan(2.2);
    expect(totalWeight(after)).toBeCloseTo(totalWeight(before), 2);
  });

  it("減らす向きでも他の軸へ比率どおりに配り、合計は変わらない", () => {
    const before = { a: 0.4, b: 0.4, c: 0.2 };
    const after = adjustAxisShare(before, "a", -10)!;

    expect(after.a).toBeLessThan(before.a);
    expect(after.b).toBeGreaterThan(before.b);
    expect(after.c).toBeGreaterThan(before.c);
    expect(totalWeight(after)).toBeCloseTo(totalWeight(before), 2);
  });

  it("無効な軸（重み0）は増減の対象にならない", () => {
    const after = adjustAxisShare({ a: 0.5, b: 0.5, off: 0 }, "a", 10)!;

    expect(after.off).toBe(0);
  });

  it("按分で他の軸が0（＝無効扱い）へ落ちない", () => {
    // bは既に下限。aを増やしても、bが0になって黙ってチェックOFF相当へ化けてはいけない。
    const after = adjustAxisShare({ a: 0.5, b: MIN_AXIS_WEIGHT }, "a", 20);

    expect(after?.b ?? MIN_AXIS_WEIGHT).toBeGreaterThanOrEqual(MIN_AXIS_WEIGHT);
  });

  it("上限・下限を超えない", () => {
    const raised = adjustAxisShare({ a: MAX_AXIS_WEIGHT, b: 0.2 }, "a", 20);
    expect(raised?.a ?? MAX_AXIS_WEIGHT).toBeLessThanOrEqual(MAX_AXIS_WEIGHT);

    const lowered = adjustAxisShare({ a: MIN_AXIS_WEIGHT, b: 0.5 }, "a", -20);
    expect(lowered?.a ?? MIN_AXIS_WEIGHT).toBeGreaterThanOrEqual(MIN_AXIS_WEIGHT);
  });

  it("有効な軸が1つだけなら動かせない（常に100%のため）", () => {
    expect(adjustAxisShare({ a: 0.4, b: 0 }, "a", 10)).toBeNull();
  });

  it("無効な軸自身は動かせない", () => {
    expect(adjustAxisShare({ a: 0.4, b: 0 }, "b", 10)).toBeNull();
  });
  // 軸が多いと、比率どおりの実数を軸ごとに0.01刻みへ丸める方式では全軸ぶんの端数が
  // 消え、押しても何も動かない（＝±が常に押せない）状態になる。
  it("軸が多くても1%の増減が必ず1ステップ以上動く", () => {
    const before = { a: 0.1, b: 0.15, c: 0.15, d: 0.1, e: 0.1, f: 0.1, g: 0.1, h: 0.1 };
    const after = adjustAxisShare(before, "a", 1);

    expect(after).not.toBeNull();
    expect(after!.a).toBeGreaterThan(before.a);
    expect(totalWeight(after!)).toBeCloseTo(totalWeight(before), 2);
  });
});
