// @vitest-environment node
// DOM/MapLibreを一切使わない純粋関数のみを検証するため、jsdom環境構築コストを省く
// （docs/testing.mdパターン3）。
import { describe, expect, it } from "vitest";
import {
  buildDedicatedWayValueColorExpression,
  dedicatedWayValueColorExpression,
  dedicatedWayValueFeatureStateKey,
  dedicatedWayValueLegend,
  type DedicatedWayValueDisplay,
} from "./dedicatedWayValueLayer";
import {
  COLOR_HARD,
  COLOR_LOADING,
  COLOR_NO_DATA,
  COLOR_SIGNED_LOW,
  DEFAULT_DIFFICULTY_BOUNDARIES,
  SIGNED_MATERIAL_BOUNDARIES,
  bandColorsFor,
} from "./valueScale";

const difficultyDisplay: DedicatedWayValueDisplay = { kind: "difficulty", unit: "" };
const signedDisplay: DedicatedWayValueDisplay = { kind: "signed_material", unit: "%" };

describe("dedicatedWayValueLayer", () => {
  describe("dedicatedWayValueColorExpression", () => {
    it("feature-state未設定（null）はCOLOR_NO_DATAへ倒し、キーは軸idから機械的に導出する", () => {
      const expression = dedicatedWayValueColorExpression("wind", difficultyDisplay);
      expect(expression[0]).toBe("case");
      expect(expression[1]).toEqual(["==", ["feature-state", dedicatedWayValueFeatureStateKey("wind")], null]);
      expect(expression[2]).toBe(COLOR_NO_DATA);
      expect(dedicatedWayValueFeatureStateKey("wind")).not.toBe(dedicatedWayValueFeatureStateKey("gradient"));
    });

    it("段階数はboundaries.length+1（省略時は種類ごとの既定しきい値）", () => {
      const step = dedicatedWayValueColorExpression("wind", difficultyDisplay)[3] as unknown[];
      expect(step[0]).toBe("step");
      expect(step).toHaveLength(3 + DEFAULT_DIFFICULTY_BOUNDARIES.length * 2);

      const signedStep = dedicatedWayValueColorExpression("gradient", signedDisplay)[3] as unknown[];
      expect(signedStep).toHaveLength(3 + SIGNED_MATERIAL_BOUNDARIES.length * 2);

      const custom = dedicatedWayValueColorExpression("wind", { ...difficultyDisplay, boundaries: [10, 20, 30, 40, 50] })[3] as unknown[];
      expect(custom).toHaveLength(3 + 5 * 2);
    });

    it("表示宣言を省略すると難易度スケール（軸カタログ取得前の既定）になる", () => {
      const step = dedicatedWayValueColorExpression("wind")[3] as unknown[];
      expect(step).toHaveLength(3 + DEFAULT_DIFFICULTY_BOUNDARIES.length * 2);
    });

    it("loading省略時・falseはCOLOR_NO_DATA、trueはCOLOR_LOADINGへ倒す（改善計画T607）", () => {
      expect(dedicatedWayValueColorExpression("wind", difficultyDisplay)[2]).toBe(COLOR_NO_DATA);
      expect(dedicatedWayValueColorExpression("wind", difficultyDisplay, false)[2]).toBe(COLOR_NO_DATA);
      expect(dedicatedWayValueColorExpression("wind", difficultyDisplay, true)[2]).toBe(COLOR_LOADING);
    });
  });

  describe("buildDedicatedWayValueColorExpression（線・面で共有する色ロジック）", () => {
    it('["get","gradientValue"]のような任意の値取得式を受け取れる', () => {
      const expression = buildDedicatedWayValueColorExpression(["get", "gradientValue"], signedDisplay);
      expect(expression[1]).toEqual(["==", ["get", "gradientValue"], null]);
    });
  });

  describe("dedicatedWayValueLegend", () => {
    it("段階数はboundaries.length+1で、境界値と単位からラベルを機械的に組み立てる", () => {
      const legend = dedicatedWayValueLegend({ ...signedDisplay, boundaries: [0, 5] });
      expect(legend.map((b) => b.label)).toEqual(["0%未満", "0〜5%", "5%以上"]);
    });

    it("難易度スケールは単位なし・緑→赤、符号付き材料は青→赤で色式と同じ配色", () => {
      const difficulty = dedicatedWayValueLegend({ ...difficultyDisplay, boundaries: [33, 66] });
      expect(difficulty.map((b) => b.label)).toEqual(["33未満", "33〜66", "66以上"]);
      expect(difficulty.map((b) => b.color)).toEqual(bandColorsFor("difficulty", [33, 66]));

      const signed = dedicatedWayValueLegend(signedDisplay);
      expect(signed[0].color).toBe(COLOR_SIGNED_LOW);
      expect(signed[signed.length - 1].color).toBe(COLOR_HARD);
      expect(signed).toHaveLength(SIGNED_MATERIAL_BOUNDARIES.length + 1);
    });

    it("bandLabelsは要素数が段階数と一致する間だけ数値レンジの前に添える", () => {
      const labels = ["追い風・無風", "弱い向かい風", "向かい風", "強い向かい風", "非常に強い"];
      const legend = dedicatedWayValueLegend({ ...difficultyDisplay, boundaries: [20, 40, 60, 80], bandLabels: labels });
      expect(legend[0].label).toBe("追い風・無風（20未満）");
      expect(legend[4].label).toBe("非常に強い（80以上）");

      const mismatch = dedicatedWayValueLegend({ ...difficultyDisplay, boundaries: [33, 66], bandLabels: ["a", "b"] });
      expect(mismatch[0].label).toBe("33未満");
    });
  });
});
