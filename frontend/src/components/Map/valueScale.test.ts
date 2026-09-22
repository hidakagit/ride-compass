// @vitest-environment node
// 配色・段階分けの純粋関数のみを検証する（docs/conventions/testing.mdパターン3）。
import { describe, expect, it } from "vitest";
import { legendBandKey } from "./mapColorLegend";
import {
  bandColorsFor,
  buildSteppedColorExpression,
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

/** 符号付き材料の段。**軸の折れ線の節を0対称に開いたもの**で、backendが軸ごとに返す
 * （`domain/dynamic_way_values.py`）。ここでは形だけを借りて色の性質を見る。 */
const SIGNED_BANDS: readonly number[] = [-9, -6, -3, 3, 6, 9];

describe("valueScale", () => {
  // 色の補間は`bandColorsFor`の途中段階で、外へ口を持たない。段の数を変えたときに
  // 何が起きるかは、入口が返す段の色で確かめられる。
  describe("段の数と色の並び", () => {
    it("両端は配色の端の色そのもので、間は段の数だけ埋まる", () => {
      const colors = bandColorsFor("difficulty", [20, 40, 60, 80]);

      expect(colors).toHaveLength(5);
      expect(colors[0]).toBe(LOW);
      expect(colors.at(-1)).toBe(HIGH);
      expect(new Set(colors).size).toBe(colors.length);
    });

    it("段が1つしか無い軸では先頭の色だけになる", () => {
      expect(bandColorsFor("difficulty", [])).toEqual([LOW]);
    });

    it("段を増やしても両端は動かない（間だけが増える）", () => {
      const few = bandColorsFor("difficulty", [50]);
      const many = bandColorsFor("difficulty", [20, 40, 60, 80]);

      expect(many[0]).toBe(few[0]);
      expect(many.at(-1)).toBe(few.at(-1));
      expect(many.length).toBeGreaterThan(few.length);
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
      const colors = bandColorsFor("signed_material", SIGNED_BANDS);
      const flatIndex = SIGNED_BANDS.findIndex((boundary) => boundary > 0);
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
