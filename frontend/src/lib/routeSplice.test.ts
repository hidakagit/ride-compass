// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  differingStretches,
  spliceEdgeIds,
  stretchCoordinateRange,
  targetStretchEdgeIds,
} from "./routeSplice";

describe("differingStretches", () => {
  it("同じ道だけを通る2本には区間が無い", () => {
    expect(differingStretches(["a", "b", "c"], ["a", "b", "c"])).toEqual([]);
  });

  it("相手が通らないEdgeの連なりを1区間にする", () => {
    expect(differingStretches(["a", "b", "c"], ["a", "x", "c"])).toEqual([{ start: 1, end: 2 }]);
  });

  it("合流してまた分かれるときは区間を分ける", () => {
    const displayed = ["a", "b", "c", "d", "e"];
    const target = ["a", "p", "c", "q", "e"];

    expect(differingStretches(displayed, target)).toEqual([
      { start: 1, end: 2 },
      { start: 3, end: 4 },
    ]);
  });

  it("末尾まで分かれたままの区間も閉じる", () => {
    expect(differingStretches(["a", "b", "c"], ["a"])).toEqual([{ start: 1, end: 3 }]);
  });

  it("先頭から分かれる区間も拾う", () => {
    expect(differingStretches(["a", "b"], ["x", "b"])).toEqual([{ start: 0, end: 1 }]);
  });
});

describe("targetStretchEdgeIds", () => {
  it("区間の両端の共有Edgeを目印に相手側を切り出す", () => {
    const displayed = ["a", "b", "c"];
    const target = ["a", "x", "y", "c"];

    expect(targetStretchEdgeIds(displayed, target, { start: 1, end: 2 })).toEqual(["x", "y"]);
  });

  it("先頭から分かれる区間は相手の先頭から切り出す", () => {
    expect(targetStretchEdgeIds(["a", "b"], ["x", "y", "b"], { start: 0, end: 1 })).toEqual(["x", "y"]);
  });

  it("末尾まで分かれる区間は相手の末尾まで切り出す", () => {
    expect(targetStretchEdgeIds(["a", "b"], ["a", "x", "y"], { start: 1, end: 2 })).toEqual(["x", "y"]);
  });
});

describe("spliceEdgeIds", () => {
  it("区間を選ばなければ表示中の経路のまま", () => {
    expect(spliceEdgeIds(["a", "b", "c"], ["a", "x", "c"], [])).toEqual(["a", "b", "c"]);
  });

  it("1区間だけ差し替える", () => {
    expect(spliceEdgeIds(["a", "b", "c"], ["a", "x", "y", "c"], [{ start: 1, end: 2 }])).toEqual([
      "a",
      "x",
      "y",
      "c",
    ]);
  });

  it("複数の区間を差し替えても位置がずれない", () => {
    // 前から差し替えると、後ろの区間の位置がずれて別のEdgeを置き換えてしまう
    const displayed = ["a", "b", "c", "d", "e"];
    const target = ["a", "p", "q", "c", "r", "e"];

    const spliced = spliceEdgeIds(displayed, target, [
      { start: 1, end: 2 },
      { start: 3, end: 4 },
    ]);

    expect(spliced).toEqual(["a", "p", "q", "c", "r", "e"]);
  });

  it("すべての区間を差し替えると相手の経路になる", () => {
    const displayed = ["a", "b", "c", "d", "e"];
    const target = ["a", "p", "c", "q", "e"];

    expect(spliceEdgeIds(displayed, target, differingStretches(displayed, target))).toEqual(target);
  });
});

describe("stretchCoordinateRange", () => {
  it("Edgeの境界点の位置から座標の範囲を出す", () => {
    // Edge 3本、各Edgeが2点で境界を共有 → 座標は4点、境界は[0,1,2,3]
    expect(stretchCoordinateRange([0, 1, 2, 3], { start: 1, end: 2 })).toEqual({ start: 1, end: 2 });
  });

  it("対応が取れないときは描かない", () => {
    // 境界点の件数がEdge数と合っていない（backendとフロントで食い違っている）
    expect(stretchCoordinateRange([0, 1], { start: 1, end: 3 })).toBeNull();
    expect(stretchCoordinateRange([], { start: 0, end: 1 })).toBeNull();
    // 境界点が前後している（backendが返した対応が壊れている）
    expect(stretchCoordinateRange([5, 3], { start: 0, end: 1 })).toBeNull();
  });
});
