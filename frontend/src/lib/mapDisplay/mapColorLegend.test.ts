// @vitest-environment node
/**
 * `lib/mapDisplay/mapColorLegend.ts`——地図の色分けの凡例の段（鍵・範囲の文字・体感ラベル・色）の組み立て。入口は
 * `buildRangeLegendBands`と`bandLabelsForBandCount`で、確かめるのは戻り値。
 *
 * ここで見ないもの:
 * - 段の色の決め方と、段の下限 → `valueScale.test.ts`
 * - 凡例の行が地図のどの道に当てはまるか → `routeStyleModes.test.ts`・`features/map/view/lens.test.ts`
 * - 値が無い行（`NO_DATA_LEGEND_BAND`）を凡例の末尾に足すこと → それを足す凡例ごとのテスト
 */
import { describe, expect, it } from "vitest";

import { bandLabelsForBandCount, buildRangeLegendBands } from "./mapColorLegend";

const COLORS = ["#000001", "#000002", "#000003"];

describe("buildRangeLegendBands", () => {
  it("色1つにつき段を1つ作り、境界を「未満」「〜」「以上」（境界ちょうどは上の段）の範囲にする", () => {
    expect(buildRangeLegendBands([-2, 2], COLORS, "%")).toEqual([
      { key: "step-0", label: "-2%未満", color: "#000001" },
      { key: "step-1", label: "-2〜2%", color: "#000002" },
      { key: "step-2", label: "2%以上", color: "#000003" },
    ]);
  });

  it("体感ラベルを渡すと、範囲の前に添える", () => {
    const bands = buildRangeLegendBands([2, 6], COLORS, "m/s", ["弱い", "中くらい", "強い"]);

    expect(bands.map((band) => band.label)).toEqual(["弱い[2m/s未満]", "中くらい[2〜6m/s]", "強い[6m/s以上]"]);
  });

  it("段の鍵は並びの位置だけで決まり、単位・ラベル・境界の値が違っても同じ段は同じ鍵になる", () => {
    const keys = (bands: { key: string }[]) => bands.map((band) => band.key);

    expect(keys(buildRangeLegendBands([10, 20], COLORS, "", ["a", "b", "c"]))).toEqual(
      keys(buildRangeLegendBands([-5, 0], COLORS, "%")),
    );
    expect(new Set(keys(buildRangeLegendBands([10, 20], COLORS, ""))).size).toBe(COLORS.length);
  });

  it("境界が無く段が1つなら、範囲の文字を空にする", () => {
    expect(buildRangeLegendBands([], ["#000001"], "%")).toEqual([{ key: "step-0", label: "", color: "#000001" }]);
  });
});

describe("bandLabelsForBandCount", () => {
  it("体感ラベルは段の数と同じ件数のときだけ使い、多くても少なくても捨てる", () => {
    const labels = ["低", "中", "高"];

    expect(bandLabelsForBandCount(labels, 3)).toEqual(labels);
    expect(bandLabelsForBandCount(labels, 2)).toBeUndefined();
    expect(bandLabelsForBandCount(labels, 4)).toBeUndefined();
  });

  it("体感ラベルを持たない軸（null）は、ラベル無しで返す", () => {
    expect(bandLabelsForBandCount(null, 3)).toBeUndefined();
  });
});
