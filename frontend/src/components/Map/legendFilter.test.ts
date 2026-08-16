import { describe, expect, it } from "vitest";
import { summarizeLegendFilters, summarizeLegendFilterSwatches, type LegendEntry } from "./legendFilter";

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

describe("summarizeLegendFilterSwatches", () => {
  const legend5 = makeLegend(["A", "B", "C", "D", "E"]);

  it("絞り込みが無ければ空配列", () => {
    expect(summarizeLegendFilterSwatches([{ label: "路面の種類", legend: legend5, hiddenKeys: [] }])).toEqual([]);
  });

  it("表示中カテゴリが2件以下なら、その表示中カテゴリをexcluded:falseで返す", () => {
    const result = summarizeLegendFilterSwatches([
      { label: "路面の種類", legend: legend5, hiddenKeys: ["k2", "k3", "k4"] },
    ]);
    expect(result).toEqual([{ excluded: false, entries: [legend5[0], legend5[1]] }]);
  });

  it("除外カテゴリが2件以下なら、その除外カテゴリをexcluded:trueで返す", () => {
    const result = summarizeLegendFilterSwatches([{ label: "路面の種類", legend: legend5, hiddenKeys: ["k0"] }]);
    expect(result).toEqual([{ excluded: true, entries: [legend5[0]] }]);
  });

  it("軸名フォールバック（表示中・除外とも3件以上、またはすべて非表示）はスウォッチに寄与しない", () => {
    const legend7 = makeLegend(["A", "B", "C", "D", "E", "F", "G"]);
    expect(
      summarizeLegendFilterSwatches([{ label: "路面の種類", legend: legend7, hiddenKeys: ["k0", "k1", "k2"] }]),
    ).toEqual([]);
    expect(
      summarizeLegendFilterSwatches([
        { label: "路面の種類", legend: legend5, hiddenKeys: ["k0", "k1", "k2", "k3", "k4"] },
      ]),
    ).toEqual([]);
  });
});
