// @vitest-environment node
import { describe, expect, it } from "vitest";
import { buildCombinedLegendFilterExpression, summarizeLegendFilters, type LegendEntry } from "./legendFilter";

function makeLegend(labels: string[]): LegendEntry[] {
  return labels.map((label, i) => ({
    key: `k${i}`,
    label,
    color: "#000",
    filter: ["literal", true],
  }));
}

describe("summarizeLegendFilters", () => {
  const legend5 = makeLegend(["A", "B", "C", "D", "E"]);

  it("絞り込みが無ければnull", () => {
    expect(summarizeLegendFilters([{ label: "路面の種類", legend: legend5, hiddenKeys: [] }])).toBeNull();
  });

  it("表示中カテゴリが2件以下なら「◯・◯のみ」", () => {
    expect(
      summarizeLegendFilters([{ label: "路面の種類", legend: legend5, hiddenKeys: ["k2", "k3", "k4"] }]),
    ).toBe("A・Bのみ");
  });

  it("除外カテゴリが2件以下（表示中は3件以上）なら「◯以外」", () => {
    expect(summarizeLegendFilters([{ label: "路面の種類", legend: legend5, hiddenKeys: ["k0"] }])).toBe("A以外");
  });

  it("表示中・除外とも3件以上なら軸名のフォールバック文言", () => {
    const legend7 = makeLegend(["A", "B", "C", "D", "E", "F", "G"]);
    expect(
      summarizeLegendFilters([{ label: "路面の種類", legend: legend7, hiddenKeys: ["k0", "k1", "k2"] }]),
    ).toBe("路面の種類を絞り込み中");
  });

  it("全カテゴリ非表示は「すべて非表示」", () => {
    expect(
      summarizeLegendFilters([
        { label: "路面の種類", legend: legend5, hiddenKeys: ["k0", "k1", "k2", "k3", "k4"] },
      ]),
    ).toBe("路面の種類をすべて非表示");
  });

  it("複数軸は／で連結し、絞り込みの無い軸はスキップする", () => {
    // 4カテゴリ中1つ非表示 → 表示中3件(>2)・除外1件(≤2)で「以外」表現になる軸
    const highway = makeLegend(["幹線道路", "主要道", "生活道路", "農道・林道"]);
    expect(
      summarizeLegendFilters([
        { label: "路面の種類", legend: legend5, hiddenKeys: [] },
        { label: "道路の種類", legend: highway, hiddenKeys: ["k0"] },
      ]),
    ).toBe("幹線道路以外");
    expect(
      summarizeLegendFilters([
        { label: "路面の種類", legend: legend5, hiddenKeys: ["k2", "k3", "k4"] },
        { label: "道路の種類", legend: highway, hiddenKeys: ["k0"] },
      ]),
    ).toBe("A・Bのみ／幹線道路以外");
  });

  it("凡例に存在しない非表示キーは無視する（定義変更で過去のキーが残っていても安全）", () => {
    expect(summarizeLegendFilters([{ label: "路面の種類", legend: legend5, hiddenKeys: ["zombie"] }])).toBeNull();
  });
});

// 改善計画T101: stopPoi/supplyPoiが同じベクタタイルのkind値集合を分け合うために追加した
// baseFilter（非表示操作の有無に関わらず常にANDする恒常的な絞り込み）の検証。
describe("buildCombinedLegendFilterExpression", () => {
  const legend3 = makeLegend(["A", "B", "C"]);

  it("baseFilter・hiddenKeysどちらも無ければnull（既存挙動を壊さない回帰確認）", () => {
    expect(buildCombinedLegendFilterExpression([{ legend: legend3, hiddenKeys: [] }])).toBeNull();
  });

  it("baseFilterのみ（非表示操作なし）でもbaseFilterがそのまま適用される", () => {
    const baseFilter = ["in", ["get", "kind"], ["literal", ["x", "y"]]];
    expect(buildCombinedLegendFilterExpression([{ legend: legend3, hiddenKeys: [], baseFilter }])).toEqual(
      baseFilter,
    );
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
