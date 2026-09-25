// @vitest-environment node
/**
 * `valueScale.ts`——段の色が配色の端の色から段の数だけ補間され、符号付き材料は0を含む段を平坦の色にすること。
 *
 * 色の値はbackendの宣言（生成物の配色）から読む。
 */
import { describe, expect, it } from "vitest";
import palette from "@/types/generated/palette.json";
import { bandColorsFor } from "./valueScale";

const LOW = palette.semantic.evaluation_good;
const HIGH = palette.semantic.evaluation_extreme;
const DESCENT = palette.semantic.signed_descent;
/** 平坦は評価の「良い」側と同じ色。 */
const FLAT = palette.semantic.evaluation_good;

/** 符号付き材料の段。**軸の折れ線の節を0対称に開いたもの**で、backendが軸ごとに返す
 * （`domain/dynamic_way_values.py`）。ここでは形だけを借りて色の性質を見る。 */
const SIGNED_BANDS: readonly number[] = [-9, -6, -3, 3, 6, 9];

describe("valueScale", () => {
  describe("段の数と色の並び", () => {
    it("両端は配色の端の色そのもので、間は段の数だけ埋まる", () => {
      const colors = bandColorsFor("difficulty", [20, 40, 60, 80]);

      expect(colors).toHaveLength(5);
      expect(colors[0]).toBe(LOW);
      expect(colors.at(-1)).toBe(HIGH);
      expect(new Set(colors).size).toBe(colors.length);
    });

    it("段の数が配色の中継点の数と同じなら、段の色は中継点そのもの（易しい側の2段が同じ色味に寄らない）", () => {
      expect(bandColorsFor("difficulty", [25, 50, 75])).toEqual([
        palette.semantic.evaluation_good,
        palette.semantic.evaluation_mid,
        palette.semantic.evaluation_bad,
        palette.semantic.evaluation_extreme,
      ]);
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
  });
});
