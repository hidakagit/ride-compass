// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  deserializeHiddenLegendKeys,
  hiddenKeysOf,
  presentHiddenKeys,
  toggleHiddenKey,
  withHiddenKeys,
} from "./legendFilters";

describe("凡例で隠した行の保存先", () => {
  it("軸ごとに隠した鍵を持ち、無い軸は空", () => {
    expect(hiddenKeysOf({ a: ["x"] }, "a")).toEqual(["x"]);
    expect(hiddenKeysOf({ a: ["x"] }, "b")).toEqual([]);
  });

  it("書き換えは他の軸を残し、空にした軸も空の並びとして残す（最初に隠す行へ戻さない）", () => {
    expect(withHiddenKeys({ a: ["x"], b: ["y"] }, "a", ["z"])).toEqual({ a: ["z"], b: ["y"] });
    expect(withHiddenKeys({ a: ["x"], b: ["y"] }, "a", [])).toEqual({ a: [], b: ["y"] });
  });

  it("行を押すたびに隠す・戻すが入れ替わる", () => {
    const hidden = toggleHiddenKey({}, "a", "x");
    expect(hidden).toEqual({ a: ["x"] });
    expect(toggleHiddenKey(toggleHiddenKey(hidden, "a", "y"), "a", "x")).toEqual({ a: ["y"] });
  });

  it("いまの凡例に無い鍵（段の綴りや段数が変わる前の保存値）は、隠した行に数えない", () => {
    expect(presentHiddenKeys([{ key: "x" }, { key: "y" }], ["y", "gone"])).toEqual(["y"]);
  });

  it("保存値は、文字列の並びを持つ軸だけを読み、それ以外は捨てる", () => {
    expect(deserializeHiddenLegendKeys(JSON.stringify({ a: ["x"], b: [], c: [1], d: "x" }), {})).toEqual({
      a: ["x"],
      b: [],
    });
    expect(deserializeHiddenLegendKeys("null", {})).toBeNull();
    expect(deserializeHiddenLegendKeys("3", {})).toBeNull();
  });

  it("保存値に無い軸は最初に隠す行のまま、保存値にある軸は空の並びも含めて保存値のとおり", () => {
    const initial = { untouched: ["nodata"], shown: ["nodata"] };
    expect(deserializeHiddenLegendKeys(JSON.stringify({ shown: [] }), initial)).toEqual({
      untouched: ["nodata"],
      shown: [],
    });
  });
});
