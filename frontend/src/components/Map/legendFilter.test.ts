// @vitest-environment node
import { describe, expect, it } from "vitest";
import { buildCombinedLegendFilterExpression, type LegendEntry } from "./legendFilter";

function makeLegend(labels: string[]): LegendEntry[] {
  return labels.map((label, i) => ({
    key: `k${i}`,
    label,
    color: "#000",
    filter: ["literal", true],
  }));
}

describe("buildCombinedLegendFilterExpression", () => {
  const legend3 = makeLegend(["A", "B", "C"]);

  it("baseFilter・hiddenKeysどちらも無ければnull（既存挙動を壊さない回帰確認）", () => {
    expect(buildCombinedLegendFilterExpression([{ legend: legend3, hiddenKeys: [] }])).toBeNull();
  });

  it("baseFilterのみ（非表示操作なし）でもbaseFilterがそのまま適用される", () => {
    const baseFilter = ["in", ["get", "kind"], ["literal", ["x", "y"]]];
    expect(buildCombinedLegendFilterExpression([{ legend: legend3, hiddenKeys: [], baseFilter }])).toEqual(baseFilter);
  });

  it("baseFilterと凡例の非表示フィルタが両方あればANDで束ねる", () => {
    const baseFilter = ["in", ["get", "kind"], ["literal", ["x", "y"]]];
    const result = buildCombinedLegendFilterExpression([{ legend: legend3, hiddenKeys: ["k0"], baseFilter }]);
    expect(result).toEqual(["all", baseFilter, ["all", ["!", legend3[0].filter]]]);
  });

  it("baseFilterを持つ軸と持たない軸が混在してもそれぞれ独立に適用される", () => {
    const baseFilter = ["in", ["get", "kind"], ["literal", ["x"]]];
    const result = buildCombinedLegendFilterExpression([
      { legend: legend3, hiddenKeys: [], baseFilter },
      { legend: legend3, hiddenKeys: ["k0"] },
    ]);
    expect(result).toEqual(["all", baseFilter, ["all", ["!", legend3[0].filter]]]);
  });
});
