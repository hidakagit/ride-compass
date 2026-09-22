// @vitest-environment node
// 配色・段階分けの純粋関数のみを検証する（docs/conventions/testing.mdパターン3）。
import { describe, expect, it } from "vitest";
import { legendBandKey } from "./mapColorLegend";
import {
  SIGNED_MATERIAL_BOUNDARIES,
  bandColorsFor,
  buildSteppedColorExpression,
  interpolateColorStops,
} from "./valueScale";

// 補間そのものを見るので、色は**テストが自分で持つ**。実装から借りると、源泉で色を
// 調整しただけでこのテストが落ちる（自分は何も変えていないのに）。
const LOW = "#16a34a";
const HIGH = "#dc2626";
const TRANSPARENT = "rgba(0,0,0,0)";
/** 符号付き材料の下り側は寒色（平坦の緑とは別系統）。 */
const DESCENT = "#0284c7";
/** 平坦は評価の「良い」側と同じ色を使う（0付近が最も走りやすい）。 */
const FLAT = "#16a34a";

describe("valueScale", () => {
  describe("interpolateColorStops", () => {
    it("中継点を通り、両端は中継点の端の色そのものになる", () => {
      const colors = interpolateColorStops([LOW, HIGH], 5);
      expect(colors[0]).toBe(LOW);
      expect(colors[colors.length - 1]).toBe(HIGH);
      expect(colors).toHaveLength(5);
    });

    it("count=1は先頭の色だけを返す（段階が1つしか無い軸）", () => {
      expect(interpolateColorStops([LOW, HIGH], 1)).toEqual([LOW]);
    });
  });

  describe("bandColorsFor（符号付き材料は0を境に配色を分ける）", () => {
    it("0をまたぐ段階が平坦色になり、その手前は下り側の配色、その先は上り側の配色", () => {
      const boundaries = [-5, -1, 1, 5];
      const colors = bandColorsFor("signed_material", boundaries);
      expect(colors).toHaveLength(boundaries.length + 1);
      expect(colors[0]).toBe(DESCENT);
      // -1〜1（0をまたぐ段階）が分かれ目。
      expect(colors[2]).toBe(FLAT);
      expect(colors[2]).not.toBe(colors[3]);
    });

    it("段階を細かくしても、0をまたぐ段階の色は平坦色のまま動かない", () => {
      const colors = bandColorsFor("signed_material", SIGNED_MATERIAL_BOUNDARIES);
      const flatIndex = SIGNED_MATERIAL_BOUNDARIES.findIndex((boundary) => boundary > 0);
      expect(colors[flatIndex]).toBe(FLAT);
      expect(new Set(colors).size).toBe(colors.length);
    });

    it("境界がすべて正／すべて負／0を含む／0件でも段階数ぶんの色を返す", () => {
      expect(bandColorsFor("signed_material", [1, 3])).toHaveLength(3);
      expect(bandColorsFor("signed_material", [1, 3])[0]).toBe(FLAT);
      expect(bandColorsFor("signed_material", [-5, -2])).toHaveLength(3);
      expect(bandColorsFor("signed_material", [-5, -2])[2]).toBe(FLAT);
      // 境界にちょうど0がある場合は「0から始まる段階」を平坦側として扱う。
      expect(bandColorsFor("signed_material", [-2, 0, 2])[2]).toBe(FLAT);
      expect(bandColorsFor("signed_material", [])).toEqual([FLAT]);
    });

    it("難易度スケールは緑→赤のままで、符号付き材料の変更に巻き込まれない", () => {
      const colors = bandColorsFor("difficulty", [33, 66]);
      expect(colors[0]).toBe(LOW);
      expect(colors[colors.length - 1]).toBe(HIGH);
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
      expect(step[2]).not.toBe(TRANSPARENT);
      expect(step[4]).toBe(TRANSPARENT);
      expect(step[6]).not.toBe(TRANSPARENT);
    });
  });
});
