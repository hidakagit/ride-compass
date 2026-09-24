// @vitest-environment node
/**
 * `breakpointTools.ts`——折れ点の自動生成とその逆、区分線形補間、折れ点の追加位置、ドラッグの刻み。
 *
 * 補間の期待値は backend の評価（`domain/axis_templates.py: evaluate_breakpoint_linear` が使う `np.interp`）
 * の実測値。同じ折れ点を与えた画面とbackendとで値が食い違わないことが、補間の約束である。
 *
 * ここで見ないもの:
 * - 生成・補間を画面のどこで使うか → `AxisScoringSection.test.tsx`
 */
import { describe, expect, it } from "vitest";

import {
  BREAKPOINT_SHAPE_OPTIONS,
  breakpointScore,
  generateBreakpoints,
  generatorSettingsFrom,
  insertBreakpointAtLargestGap,
  interpolateBreakpointScore,
  niceStep,
  snapToStep,
} from "./breakpointTools";

const shapes = BREAKPOINT_SHAPE_OPTIONS.map((option) => option.id);

describe("generateBreakpoints", () => {
  it("効き方の選択肢が1つ以上ある", () => {
    expect(shapes.length).toBeGreaterThan(0);
  });

  it.each(shapes)("%s: 0点の値で0点・100点の値で100点になり、点数は単調に増え、xは昇順", (shape) => {
    const points = generateBreakpoints(2, 12, shape);

    expect(points[0]).toEqual([2, 0]);
    expect(points.at(-1)).toEqual([12, 100]);
    for (let i = 1; i < points.length; i++) {
      expect(points[i][0]).toBeGreaterThan(points[i - 1][0]);
      expect(points[i][1]).toBeGreaterThanOrEqual(points[i - 1][1]);
    }
  });

  it.each(shapes)(
    "%s: 0点の値が100点の値より大きい（値が大きいほど走りやすい軸）ときも、xは昇順で点数は下がる",
    (shape) => {
      const points = generateBreakpoints(80, 20, shape);

      expect(points[0]).toEqual([20, 100]);
      expect(points.at(-1)).toEqual([80, 0]);
      for (let i = 1; i < points.length; i++) {
        expect(points[i][0]).toBeGreaterThan(points[i - 1][0]);
        expect(points[i][1]).toBeLessThanOrEqual(points[i - 1][1]);
      }
    },
  );

  it("効き方は、一定なら直線、後半で急なら直線より下、前半で急なら直線より上、S字は前半が下で後半が上", () => {
    const inner = (shape: (typeof shapes)[number]) => generateBreakpoints(0, 100, shape).slice(1, -1);

    for (const [x, y] of inner("flat")) expect(y).toBeCloseTo(x, 0);
    for (const [x, y] of inner("back_loaded")) expect(y).toBeLessThan(x);
    for (const [x, y] of inner("front_loaded")) expect(y).toBeGreaterThan(x);
    const sCurve = inner("s_curve");
    expect(sCurve.filter(([x]) => x < 50).every(([x, y]) => y < x)).toBe(true);
    expect(sCurve.filter(([x]) => x > 50).every(([x, y]) => y > x)).toBe(true);
  });

  it("xは小数2桁、点数は整数へ丸める", () => {
    for (const [x, y] of generateBreakpoints(0, 1 / 3, "back_loaded")) {
      expect(Math.round(x * 100) / 100).toBe(x);
      expect(Number.isInteger(y)).toBe(true);
    }
  });
});

describe("generatorSettingsFrom", () => {
  it.each(shapes.flatMap((shape) => [[shape, 3, 15] as const, [shape, 40, 5] as const]))(
    "%s（0点 %d・100点 %d）で生成した折れ点からは、同じ3入力を一致として復元する",
    (shape, zeroValue, hundredValue) => {
      expect(generatorSettingsFrom(generateBreakpoints(zeroValue, hundredValue, shape))).toEqual({
        zeroValue,
        hundredValue,
        shape,
        matched: true,
      });
    },
  );

  it("並びが崩れていても、並べ直してから復元する", () => {
    const points = generateBreakpoints(3, 15, "front_loaded").reverse();
    expect(generatorSettingsFrom(points)).toMatchObject({ zeroValue: 3, hundredValue: 15, matched: true });
  });

  it("手で直した折れ点は、一致とせず効き方を一定にし、端点は点数の低い側を0点として復元する", () => {
    expect(
      generatorSettingsFrom([
        [0, 10],
        [4, 70],
        [9, 90],
      ]),
    ).toEqual({ zeroValue: 0, hundredValue: 9, shape: "flat", matched: false });
    expect(
      generatorSettingsFrom([
        [0, 90],
        [4, 30],
        [9, 10],
      ]),
    ).toEqual({ zeroValue: 9, hundredValue: 0, shape: "flat", matched: false });
  });

  it("両端の点数が同じなら、xの小さい側を0点とする", () => {
    expect(
      generatorSettingsFrom([
        [1, 50],
        [5, 80],
        [8, 50],
      ]),
    ).toMatchObject({ zeroValue: 1, hundredValue: 8, matched: false });
  });

  it("点が2つ未満なら、端点は0と10・効き方は一定で、一致とはしない", () => {
    expect(generatorSettingsFrom([[5, 50]])).toEqual({ zeroValue: 0, hundredValue: 10, shape: "flat", matched: false });
  });
});

describe("breakpointScore（backendの np.interp と同じ値）", () => {
  const points: [number, number][] = [
    [0, 0],
    [10, 40],
    [20, 100],
  ];

  it("範囲の外は両端の点数に留める", () => {
    expect(breakpointScore(points, -5)).toBe(0);
    expect(breakpointScore(points, 25)).toBe(100);
  });

  it("点の間は直線で補間し、丸めない", () => {
    expect(breakpointScore(points, 5)).toBe(20);
    expect(breakpointScore(points, 12.5)).toBe(55);
    expect(breakpointScore(points, 1 / 3)).toBeCloseTo(4 / 3, 12);
  });

  it("並びが崩れた折れ点も、並べ直して補間する", () => {
    expect(breakpointScore([points[2], points[0], points[1]], 15)).toBe(70);
  });

  it("折れ点が無ければ0点", () => {
    expect(breakpointScore([], 3)).toBe(0);
  });
});

describe("interpolateBreakpointScore", () => {
  it("補間した値を小数1桁へ丸める", () => {
    const points: [number, number][] = [
      [0, 0],
      [3, 10],
    ];
    expect(interpolateBreakpointScore(points, 1)).toBe(3.3);
    expect(interpolateBreakpointScore(points, 2)).toBe(6.7);
  });
});

describe("insertBreakpointAtLargestGap", () => {
  it("隣どうしのxの間隔が最も広い区間の中点へ、xは小数2桁・点数は整数で挿す", () => {
    const next = insertBreakpointAtLargestGap([
      [0, 0],
      [1, 10],
      [4.02, 55],
      [5, 100],
    ]);
    expect(next).toEqual([
      [0, 0],
      [1, 10],
      [2.51, 33],
      [4.02, 55],
      [5, 100],
    ]);
  });

  it("並びが崩れていても、足した後の並びはxの昇順", () => {
    const next = insertBreakpointAtLargestGap([
      [10, 100],
      [0, 0],
      [2, 20],
    ]);
    expect(next.map(([x]) => x)).toEqual([0, 2, 6, 10]);
  });

  it("最も広い間隔が複数あれば、xの小さい側に挿す", () => {
    const next = insertBreakpointAtLargestGap([
      [0, 0],
      [2, 20],
      [4, 40],
    ]);
    expect(next.map(([x]) => x)).toEqual([0, 1, 2, 4]);
  });
});

describe("並べ直しは渡された配列を書き換えない（下書きの折れ点をそのまま渡すため）", () => {
  it("折れ点を足しても、渡した下書きの折れ点は元の並びのまま", () => {
    const points: [number, number][] = [
      [10, 100],
      [0, 0],
      [4, 30],
    ];
    const before = structuredClone(points);
    insertBreakpointAtLargestGap(points);
    expect(points).toEqual(before);
  });
});

describe("niceStep", () => {
  it.each([
    [20, 1],
    [40, 2],
    [100, 5],
    [180, 10],
    [0.5, 0.02],
  ])("表示の幅 %d には、目盛り20個ぶんに近い 1・2・5×10^n の刻み %d を選ぶ", (span, step) => {
    expect(niceStep(span)).toBeCloseTo(step, 12);
  });

  it("目盛りの数を変えれば、刻みも変わる", () => {
    expect(niceStep(100, 10)).toBe(10);
  });

  it.each([[0], [-3], [Number.NaN], [Number.POSITIVE_INFINITY]])("幅が %d なら刻みは1", (span) => {
    expect(niceStep(span)).toBe(1);
  });
});

describe("snapToStep", () => {
  it("値を刻みの倍数へ丸める", () => {
    expect(snapToStep(7.4, 5)).toBe(5);
    expect(snapToStep(7.6, 5)).toBe(10);
  });

  it("刻みが0以下なら丸めない", () => {
    expect(snapToStep(7.4, 0)).toBe(7.4);
    expect(snapToStep(7.4, -1)).toBe(7.4);
  });
});
