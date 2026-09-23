// @vitest-environment node
// `legendFilters.ts`——凡例で隠した行の保存先の読み書きと、地図の各家族への振り分け。
//
// ここで見ないもの: 隠した行が地図の式へどう効くか → `scene/groups/*.test.ts`
import { describe, expect, it } from "vitest";

import { catalogOf, dedicatedEntry, rampEntry } from "./__fixtures__/catalog";
import {
  deserializeHiddenLegendKeys,
  mapHiddenKeysFrom,
  presentHiddenKeys,
  serializeHiddenLegendKeys,
  toggleHiddenKey,
  withHiddenKeys,
} from "./legendFilters";

describe("隠した行の切り替え", () => {
  it("押すたびに隠す・戻すが入れ替わり、最後の1行を戻すと保存先から鍵ごと消える", () => {
    const hidden = toggleHiddenKey({}, "a", "k1");
    expect(hidden).toEqual({ a: ["k1"] });
    expect(toggleHiddenKey(hidden, "a", "k2")).toEqual({ a: ["k1", "k2"] });
    expect(toggleHiddenKey(hidden, "a", "k1")).toEqual({});
  });

  it("まとめて置き換えるときも、空にした鍵は消す", () => {
    expect(withHiddenKeys({ a: ["k1"], b: ["k2"] }, "a", [])).toEqual({ b: ["k2"] });
  });
});

describe("presentHiddenKeys（いま描いている凡例に実在する鍵）", () => {
  it("凡例に無い古い鍵は数えない", () => {
    const legend = [{ key: "step-0", label: "", color: "#000" }];
    expect(presentHiddenKeys(legend, ["step-0", "gone"])).toEqual(["step-0"]);
    expect(presentHiddenKeys(legend, ["gone"])).toEqual([]);
  });
});

describe("保存値の読み書き", () => {
  it("書いた値をそのまま読み戻せる", () => {
    const hidden = { a: ["k1"], b: ["k2", "k3"] };
    expect(deserializeHiddenLegendKeys(serializeHiddenLegendKeys(hidden))).toEqual(hidden);
  });

  it("形の合わない保存値は読まず、合わない要素だけを落とす", () => {
    expect(deserializeHiddenLegendKeys("not json")).toBeNull();
    expect(deserializeHiddenLegendKeys("[]")).toBeNull();
    expect(deserializeHiddenLegendKeys(JSON.stringify({ a: ["k1", 3], b: "k2", c: [] }))).toEqual({ a: ["k1"] });
  });
});

describe("mapHiddenKeysFrom（地図の各家族への振り分け）", () => {
  const catalog = catalogOf([rampEntry("r", [1]), dedicatedEntry("d", [0])]);

  it("ramp軸の隠した段はタイルの絞り込みへ、専用配信軸の隠した段は色式の側へ渡す", () => {
    const result = mapHiddenKeysFrom({ r: ["step-0"], d: ["step-1"] }, catalog.rampAxes, catalog.dedicatedAxes);
    expect(result.staticLegendHiddenKeysByAxis.r).toEqual(["step-0"]);
    expect(result.dedicatedWayValueHiddenBands.get("d")).toEqual(["step-1"]);
    expect(result.staticLegendHiddenKeysByAxis.d).toBeUndefined();
  });

  it("道路の線の凡例で隠した行は、道路の線の絞り込みへ渡す", () => {
    const [roadAxisId] = Object.keys(mapHiddenKeysFrom({}, [], []).roadHiddenKeysByMode);
    expect(roadAxisId).toBeDefined();
    const result = mapHiddenKeysFrom({ [roadAxisId]: ["k"] }, [], []);
    expect(result.roadHiddenKeysByMode[roadAxisId]).toEqual(["k"]);
    expect(result.staticLegendHiddenKeysByAxis[roadAxisId]).toBeUndefined();
  });
});
