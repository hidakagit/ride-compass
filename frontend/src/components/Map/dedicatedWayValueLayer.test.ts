// @vitest-environment node
// DOM/MapLibreを一切使わない純粋関数のみを検証するため、jsdom環境構築コストを省く
// （docs/conventions/testing.mdパターン3）。地図の線の色は`scene/groups/axisLines.test.ts`が見る。
import { describe, expect, it } from "vitest";
import { dedicatedWayValueLegend, type DedicatedWayValueDisplay } from "./dedicatedWayValueLayer";
import { COLOR_NO_DATA, bandColorsFor } from "./valueScale";
import { LEGEND_NO_DATA_KEY } from "./mapColorLegend";

/** 符号付き材料の段。**軸の折れ線の節を0対称に開いたもの**で、backendが軸ごとに返す
 * （`domain/dynamic_way_values.py`）。ここでは形だけを借りて色の性質を見る。 */
const SIGNED_BANDS: readonly number[] = [-9, -6, -3, 3, 6, 9];

const difficultyDisplay: DedicatedWayValueDisplay = { kind: "difficulty", unit: "" };
const signedDisplay: DedicatedWayValueDisplay = { kind: "signed_material", unit: "%", boundaries: SIGNED_BANDS };

// 下り側は寒色、平坦は緑、という**性質**を見る。実装の定数を借りると、源泉で色を
// 調整しただけで落ちる。
const DESCENT = "#0284c7";
const FLAT = "#16a34a";

describe("dedicatedWayValueLegend", () => {
  it("段階数はboundaries.length+1で、境界値と単位からラベルを機械的に組み立てる（末尾はデータなし）", () => {
    const legend = dedicatedWayValueLegend({ ...signedDisplay, boundaries: [0, 5] });
    expect(legend.map((b) => b.label)).toEqual(["0%未満", "0〜5%", "5%以上", "データなし"]);
    expect(legend[legend.length - 1].key).toBe(LEGEND_NO_DATA_KEY);
    expect(legend[legend.length - 1].color).toBe(COLOR_NO_DATA);
  });

  it("難易度スケールは単位なし・緑→赤、符号付き材料は0を境に下り側・上り側で配色を分ける", () => {
    const difficulty = dedicatedWayValueLegend({ ...difficultyDisplay, boundaries: [33, 66] });
    expect(difficulty.slice(0, -1).map((b) => b.label)).toEqual(["33未満", "33〜66", "66以上"]);
    expect(difficulty.slice(0, -1).map((b) => b.color)).toEqual(bandColorsFor("difficulty", [33, 66]));

    const signed = dedicatedWayValueLegend(signedDisplay);
    expect(signed[0].color).toBe(DESCENT);
    // 0をまたぐ段階（平坦）が配色の分かれ目。
    const flatIndex = SIGNED_BANDS.findIndex((boundary) => boundary > 0);
    expect(signed[flatIndex].color).toBe(FLAT);
    expect(signed).toHaveLength(SIGNED_BANDS.length + 2);
  });

  it("bandLabelsは要素数が段階数と一致する間だけ数値レンジの前に添える", () => {
    const labels = ["追い風・無風", "弱い向かい風", "向かい風", "強い向かい風", "非常に強い"];
    const legend = dedicatedWayValueLegend({
      ...difficultyDisplay,
      boundaries: [20, 40, 60, 80],
      bandLabels: labels,
    });
    expect(legend[0].label).toBe("追い風・無風（20未満）");
    expect(legend[4].label).toBe("非常に強い（80以上）");

    const mismatch = dedicatedWayValueLegend({ ...difficultyDisplay, boundaries: [33, 66], bandLabels: ["a", "b"] });
    expect(mismatch[0].label).toBe("33未満");
  });
});
