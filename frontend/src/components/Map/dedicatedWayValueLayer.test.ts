// @vitest-environment node
// DOM/MapLibreを一切使わない純粋関数のみを検証するため、jsdom環境構築コストを省く
// （docs/conventions/testing.mdパターン3）。
import { describe, expect, it } from "vitest";
import {
  buildDedicatedWayValueColorExpression,
  dedicatedWayValueColorExpression,
  dedicatedWayValueLegend,
  type DedicatedWayValueDisplay,
} from "./dedicatedWayValueLayer";
import { COLOR_LOADING, COLOR_NO_DATA, DEFAULT_DIFFICULTY_BOUNDARIES, bandColorsFor } from "./valueScale";
import { LEGEND_NO_DATA_KEY, legendBandKey } from "./mapColorLegend";

/** 符号付き材料の段。**軸の折れ線の節を0対称に開いたもの**で、backendが軸ごとに返す
 * （`domain/dynamic_way_values.py`）。ここでは形だけを借りて色の性質を見る。 */
const SIGNED_BANDS: readonly number[] = [-9, -6, -3, 3, 6, 9];

const difficultyDisplay: DedicatedWayValueDisplay = { kind: "difficulty", unit: "" };
const signedDisplay: DedicatedWayValueDisplay = { kind: "signed_material", unit: "%", boundaries: SIGNED_BANDS };

// 隠した段は透明、下り側は寒色、という**性質**を見る。実装の定数を借りると、源泉で色を
// 調整しただけで落ちる。
const TRANSPARENT = "rgba(0,0,0,0)";
const DESCENT = "#0284c7";
const FLAT = "#16a34a";

describe("dedicatedWayValueLayer", () => {
  describe("dedicatedWayValueColorExpression", () => {
    it("feature-state未設定（null）はCOLOR_NO_DATAへ倒し、キーは軸ごとに別になる", () => {
      const expression = dedicatedWayValueColorExpression("wind", difficultyDisplay);

      expect(expression[0]).toBe("case");
      expect(expression[1]).toEqual(["==", ["feature-state", expect.any(String)], null]);
      expect(expression[2]).toBe(COLOR_NO_DATA);
      // 同じソースへ複数の軸が値を載せるので、軸ごとに別のキーを読む必要がある。
      // **キーの綴りは借りない**——式の中に現れる名前が軸で変わることだけを見る。
      expect(JSON.stringify(expression[1])).not.toBe(
        JSON.stringify(dedicatedWayValueColorExpression("gradient", difficultyDisplay)[1]),
      );
    });

    it("段階数はboundaries.length+1（省略時は難易度の既定）", () => {
      const step = dedicatedWayValueColorExpression("wind", difficultyDisplay)[3] as unknown[];
      expect(step[0]).toBe("step");
      expect(step).toHaveLength(3 + DEFAULT_DIFFICULTY_BOUNDARIES.length * 2);

      const signedStep = dedicatedWayValueColorExpression("gradient", signedDisplay)[3] as unknown[];
      expect(signedStep).toHaveLength(3 + SIGNED_BANDS.length * 2);

      const custom = dedicatedWayValueColorExpression("wind", {
        ...difficultyDisplay,
        boundaries: [10, 20, 30, 40, 50],
      })[3] as unknown[];
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

  describe("段階の表示ON/OFF（hiddenBandKeys）", () => {
    it("非表示にした段階の色だけが透明になり、他の段階の色は変わらない", () => {
      const visible = dedicatedWayValueColorExpression("gradient", signedDisplay)[3] as unknown[];
      const hidden = dedicatedWayValueColorExpression("gradient", signedDisplay, false, [
        legendBandKey(0),
      ])[3] as unknown[];
      expect(hidden[2]).toBe(TRANSPARENT);
      expect(hidden.slice(3)).toEqual(visible.slice(3));
    });

    it("データなしを非表示にするとnull側が透明になる。ただしフェッチ中の色は残す", () => {
      const hidden = dedicatedWayValueColorExpression("gradient", signedDisplay, false, [LEGEND_NO_DATA_KEY]);
      expect(hidden[2]).toBe(TRANSPARENT);
      const loading = dedicatedWayValueColorExpression("gradient", signedDisplay, true, [LEGEND_NO_DATA_KEY]);
      expect(loading[2]).toBe(COLOR_LOADING);
    });

    it("凡例の段階キーと色式の段階の並びが一致する（同じキーで同じ段階を隠せる）", () => {
      const legend = dedicatedWayValueLegend(signedDisplay);
      const lastBandIndex = SIGNED_BANDS.length;
      const hidden = dedicatedWayValueColorExpression("gradient", signedDisplay, false, [
        legendBandKey(lastBandIndex),
      ])[3] as unknown[];
      expect(legend[lastBandIndex].key).toBe(legendBandKey(lastBandIndex));
      expect(hidden[hidden.length - 1]).toBe(TRANSPARENT);
    });
  });

  describe("dedicatedWayValueLegend", () => {
    it("段階数はboundaries.length+1で、境界値と単位からラベルを機械的に組み立てる（末尾はデータなし）", () => {
      const legend = dedicatedWayValueLegend({ ...signedDisplay, boundaries: [0, 5] });
      expect(legend.map((b) => b.label)).toEqual(["0%未満", "0〜5%", "5%以上", "データなし"]);
      expect(legend[legend.length - 1].key).toBe(LEGEND_NO_DATA_KEY);
      expect(legend[legend.length - 1].color).toBe(COLOR_NO_DATA);
    });

    it("難易度スケールは単位なし・緑→赤、符号付き材料は0を境に下り側・上り側で色式と同じ配色", () => {
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
});
