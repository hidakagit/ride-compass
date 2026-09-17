// @vitest-environment node
// 配色・段階分けの純粋関数のみを検証する（docs/testing.mdパターン3）。
import { describe, expect, it } from "vitest";
import { legendBandKey } from "./mapColorLegend";
import {
  COLOR_EASY,
  COLOR_HARD,
  COLOR_HIDDEN,
  COLOR_SIGNED_FLAT,
  COLOR_SIGNED_LOW,
  SIGNED_MATERIAL_BOUNDARIES,
  bandColorsFor,
  buildSteppedColorExpression,
  interpolateColorStops,
} from "./valueScale";

describe("valueScale", () => {
  describe("interpolateColorStops", () => {
    it("中継点を通り、両端は中継点の端の色そのものになる", () => {
      const colors = interpolateColorStops([COLOR_EASY, COLOR_HARD], 5);
      expect(colors[0]).toBe(COLOR_EASY);
      expect(colors[colors.length - 1]).toBe(COLOR_HARD);
      expect(colors).toHaveLength(5);
    });

    it("count=1は先頭の色だけを返す（段階が1つしか無い軸）", () => {
      expect(interpolateColorStops([COLOR_EASY, COLOR_HARD], 1)).toEqual([COLOR_EASY]);
    });
  });

  describe("bandColorsFor（符号付き材料は0を境に配色を分ける）", () => {
    it("0をまたぐ段階が平坦色になり、その手前は下り側の配色、その先は上り側の配色", () => {
      const boundaries = [-5, -1, 1, 5];
      const colors = bandColorsFor("signed_material", boundaries);
      expect(colors).toHaveLength(boundaries.length + 1);
      expect(colors[0]).toBe(COLOR_SIGNED_LOW);
      // -1〜1（0をまたぐ段階）が分かれ目。
      expect(colors[2]).toBe(COLOR_SIGNED_FLAT);
      expect(colors[2]).not.toBe(colors[3]);
    });

    it("段階を細かくしても、0をまたぐ段階の色は平坦色のまま動かない", () => {
      const colors = bandColorsFor("signed_material", SIGNED_MATERIAL_BOUNDARIES);
      const flatIndex = SIGNED_MATERIAL_BOUNDARIES.findIndex((boundary) => boundary > 0);
      expect(colors[flatIndex]).toBe(COLOR_SIGNED_FLAT);
      expect(new Set(colors).size).toBe(colors.length);
    });

    it("境界がすべて正／すべて負／0を含む／0件でも段階数ぶんの色を返す", () => {
      expect(bandColorsFor("signed_material", [1, 3])).toHaveLength(3);
      expect(bandColorsFor("signed_material", [1, 3])[0]).toBe(COLOR_SIGNED_FLAT);
      expect(bandColorsFor("signed_material", [-5, -2])).toHaveLength(3);
      expect(bandColorsFor("signed_material", [-5, -2])[2]).toBe(COLOR_SIGNED_FLAT);
      // 境界にちょうど0がある場合は「0から始まる段階」を平坦側として扱う。
      expect(bandColorsFor("signed_material", [-2, 0, 2])[2]).toBe(COLOR_SIGNED_FLAT);
      expect(bandColorsFor("signed_material", [])).toEqual([COLOR_SIGNED_FLAT]);
    });

    it("難易度スケールは緑→赤のままで、符号付き材料の変更に巻き込まれない", () => {
      const colors = bandColorsFor("difficulty", [33, 66]);
      expect(colors[0]).toBe(COLOR_EASY);
      expect(colors[colors.length - 1]).toBe(COLOR_HARD);
    });
  });

  describe("buildSteppedColorExpression（非表示段階）", () => {
    it("非表示の段階だけが透明になる", () => {
      const expression = buildSteppedColorExpression({
        valueExpression: ["feature-state", "gradientValue"],
        kind: "signed_material",
        boundaries: [-1, 1],
        hiddenBandKeys: [legendBandKey(1)],
      });
      const step = expression[3] as unknown[];
      // ["step", value, 色0, -1, 色1, 1, 色2]
      expect(step[2]).not.toBe(COLOR_HIDDEN);
      expect(step[4]).toBe(COLOR_HIDDEN);
      expect(step[6]).not.toBe(COLOR_HIDDEN);
    });
  });
});
