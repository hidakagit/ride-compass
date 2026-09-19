// @vitest-environment node
// 段階ラベルの組み立て（mapColorLegend.ts）。DOMを使わない純ロジック。
import { describe, expect, it } from "vitest";
import { buildRangeLegendBands } from "./mapColorLegend";

describe("buildRangeLegendBands", () => {
  it("境界と段階数が揃っていれば、上下の端を開いた範囲で書く", () => {
    const bands = buildRangeLegendBands([2, 6], ["#a", "#b", "#c"], "%");

    expect(bands.map((band) => band.label)).toEqual(["2%未満", "2〜6%", "6%以上"]);
  });

  it("段階に対して境界が足りなくても、読めないラベルを作らない", () => {
    // 境界の件数は段階数-1という前提が崩れる組み合わせ（軸の折れ線が飽和して境界が
    // 同じ値へ潰れると実際に起きる）。添字で引いた`undefined`をそのまま文字にすると
    // 「undefined〜undefined%」が凡例へ出る。
    const bands = buildRangeLegendBands([], ["#a", "#b"], "%");

    expect(bands.map((band) => band.label).join("")).not.toContain("undefined");
    expect(bands.map((band) => band.label).join("")).not.toContain("null");
  });

  it("体感ラベルを渡すと、数値レンジの前に添える", () => {
    const bands = buildRangeLegendBands([6], ["#a", "#b"], "m/s", ["追い風", "向かい風"]);

    expect(bands.map((band) => band.label)).toEqual(["追い風（6m/s未満）", "向かい風（6m/s以上）"]);
  });
});
