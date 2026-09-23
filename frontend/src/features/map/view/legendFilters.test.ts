// @vitest-environment node
// `legendFilters.ts`——凡例で隠した行の保存先の読み書き。
import { describe, expect, it } from "vitest";

import { deserializeHiddenLegendKeys, toggleHiddenKey, withHiddenKeys } from "./legendFilters";

describe("隠した行の切り替え", () => {
  it("押すたびに隠す・戻すが入れ替わり、最後の1行を戻すと保存先から鍵ごと消える", () => {
    const hidden = toggleHiddenKey({}, "a", "k1");
    expect(hidden).toEqual({ a: ["k1"] });
    expect(toggleHiddenKey(hidden, "a", "k1")).toEqual({});
  });

  it("まとめて置き換えるときも、空にした鍵は消し、他の鍵は残す", () => {
    expect(withHiddenKeys({ a: ["k1"], b: ["k2"] }, "a", [])).toEqual({ b: ["k2"] });
  });
});

describe("保存値の読み込み", () => {
  it("書いた値をそのまま読み戻せる", () => {
    const saved = { a: ["k1", "k2"] };
    expect(deserializeHiddenLegendKeys(JSON.stringify(saved))).toEqual(saved);
  });

  it("文字列の配列でない鍵と空の鍵は捨て、残りは読む", () => {
    expect(deserializeHiddenLegendKeys(JSON.stringify({ a: ["k1"], b: "k2", c: [1], d: [] }))).toEqual({ a: ["k1"] });
    expect(deserializeHiddenLegendKeys("null")).toBeNull();
  });
});
