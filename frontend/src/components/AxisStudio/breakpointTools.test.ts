// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  generateBreakpoints,
  insertBreakpointAtLargestGap,
  interpolateBreakpointScore,
  niceStep,
  snapToStep,
  sortBreakpoints,
} from "./breakpointTools";

describe("generateBreakpoints", () => {
  it("flat(一定)は0点〜100点まで6点を線形に生成する", () => {
    const points = generateBreakpoints(0, 10, "flat");
    expect(points).toEqual([
      [0, 0],
      [2, 20],
      [4, 40],
      [6, 60],
      [8, 80],
      [10, 100],
    ]);
  });

  it("back_loaded(後半で急)は前半のスコアが線形より低い(下に凸)", () => {
    const points = generateBreakpoints(0, 10, "back_loaded");
    expect(points[0]).toEqual([0, 0]);
    expect(points[points.length - 1]).toEqual([10, 100]);
    expect(points[1][1]).toBeLessThan(20); // t=0.2の線形値20より低い
  });

  it("front_loaded(前半で急)は前半のスコアが線形より高い(上に凸)", () => {
    const points = generateBreakpoints(0, 10, "front_loaded");
    expect(points[1][1]).toBeGreaterThan(20);
  });

  it("s_curve(S字)は両端付近がゆるやかで中心対称(smoothstep)になる", () => {
    const points = generateBreakpoints(0, 10, "s_curve");
    expect(points[1][1]).toBeLessThan(20); // 立ち上がりはゆるやか(線形なら20)
    // smoothstepは(0.5, 50)を中心に点対称——t=0.4とt=0.6のスコアの合計は必ず100になる。
    expect(points[2][1] + points[3][1]).toBe(100);
  });

  it("zeroValue > hundredValue（値が大きいほど走りやすい）でもx昇順で返す", () => {
    const points = generateBreakpoints(10, 0, "flat");
    expect(points[0]).toEqual([0, 100]);
    expect(points[points.length - 1]).toEqual([10, 0]);
    for (let i = 1; i < points.length; i++) {
      expect(points[i][0]).toBeGreaterThan(points[i - 1][0]);
    }
  });
});

describe("sortBreakpoints", () => {
  it("x昇順へ並べ替える(元の配列は変更しない)", () => {
    const original: [number, number][] = [
      [10, 100],
      [0, 0],
      [5, 50],
    ];
    const sorted = sortBreakpoints(original);
    expect(sorted).toEqual([
      [0, 0],
      [5, 50],
      [10, 100],
    ]);
    expect(original).toEqual([
      [10, 100],
      [0, 0],
      [5, 50],
    ]);
  });
});

describe("interpolateBreakpointScore", () => {
  const breakpoints: [number, number][] = [
    [0, 0],
    [10, 100],
  ];

  it("区間内は線形補間する", () => {
    expect(interpolateBreakpointScore(breakpoints, 5)).toBe(50);
    expect(interpolateBreakpointScore(breakpoints, 2.5)).toBe(25);
  });

  it("範囲外は両端でクランプする(np.interpと同じ)", () => {
    expect(interpolateBreakpointScore(breakpoints, -5)).toBe(0);
    expect(interpolateBreakpointScore(breakpoints, 100)).toBe(100);
  });

  it("小数1桁へ丸める(backend: evaluate_breakpoint_linearと同じ丸め)", () => {
    expect(interpolateBreakpointScore(breakpoints, 1)).toBe(10);
    expect(interpolateBreakpointScore([[0, 0], [3, 1]], 1)).toBeCloseTo(0.3, 5);
  });

  it("xが昇順でなくても内部でソートしてから補間する", () => {
    const unsorted: [number, number][] = [
      [10, 100],
      [0, 0],
    ];
    expect(interpolateBreakpointScore(unsorted, 5)).toBe(50);
  });
});

describe("insertBreakpointAtLargestGap", () => {
  it("唯一の区間の中間へ挿入する", () => {
    const result = insertBreakpointAtLargestGap([
      [0, 0],
      [10, 100],
    ]);
    expect(result).toEqual([
      [0, 0],
      [5, 50],
      [10, 100],
    ]);
  });

  it("最も間隔の広い区間へ挿入する(常に末尾に足すわけではない)", () => {
    const result = insertBreakpointAtLargestGap([
      [0, 0],
      [1, 10],
      [20, 100],
    ]);
    // [1,20]の区間(幅19)が[0,1](幅1)より広いためそちらへ挿入される。
    expect(result).toEqual([
      [0, 0],
      [1, 10],
      [10.5, 55],
      [20, 100],
    ]);
  });

  it("挿入後も昇順のまま保たれる", () => {
    const result = insertBreakpointAtLargestGap([
      [10, 100],
      [0, 0],
    ]);
    for (let i = 1; i < result.length; i++) {
      expect(result[i][0]).toBeGreaterThan(result[i - 1][0]);
    }
  });
});

describe("niceStep/snapToStep", () => {
  it("スパンに応じてきりのいい刻み幅を返す", () => {
    expect(niceStep(100)).toBe(5);
    expect(niceStep(10)).toBe(0.5);
    expect(niceStep(1)).toBe(0.05);
  });

  it("snapToStepは指定刻みの最も近い倍数へ丸める", () => {
    expect(snapToStep(7.3, 5)).toBe(5);
    expect(snapToStep(8.3, 5)).toBe(10);
    expect(snapToStep(3, 0)).toBe(3); // step<=0は素通し
  });
});
