// @vitest-environment node
// `lens.ts`——レンズの1つの値から、全道路を塗る軸・凡例・選択肢を導く。
//
// ここで見ないもの:
// - 凡例の段そのもの（境界・色・ラベルの規則）→ `mapColorLegend.test.ts`・`axisLayers.test.ts`
import { describe, expect, it } from "vitest";

import { catalogOf, catalogEntry, dedicatedEntry, rampEntry } from "./__fixtures__/catalog";
import { lensLegend, lensOptions, paintedAxisId } from "./lens";

// ramp表示を持つ軸・専用配信を持つ軸・どちらも持たない軸。
const CATALOG = catalogOf([rampEntry("r", [1, 2]), dedicatedEntry("d", [0]), catalogEntry({ axis_id: "p" })]);

describe("paintedAxisId（全道路を塗っている軸）", () => {
  it("ルート確定前はレンズの軸を塗り、確定後は周囲も塗り続ける設定の間だけ塗る", () => {
    expect(paintedAxisId("r", false, false)).toBe("r");
    expect(paintedAxisId("r", true, true)).toBe("r");
    expect(paintedAxisId("r", true, false)).toBeNull();
  });
});

describe("lensLegend（レンズの凡例）", () => {
  it("ルート確定前は、その軸で全道路を塗る手段の段を出す", () => {
    expect(lensLegend("r", false, CATALOG).map((entry) => entry.label)).toEqual(["1未満", "1〜2", "2以上"]);
    expect(lensLegend("d", false, CATALOG).map((entry) => entry.label)).toEqual(["0未満", "0以上", "データなし"]);
  });

  it("ルート確定の前後で段の鍵が同じなので、隠した段がルート生成をまたいで残る", () => {
    const before = lensLegend("d", false, CATALOG).map((entry) => entry.key);
    expect(lensLegend("d", true, CATALOG).map((entry) => entry.key)).toEqual(before);
  });

  it("地図がそのレンズで何も塗らない間は、凡例を出さない", () => {
    expect(lensLegend("difficulty", false, CATALOG)).toEqual([]);
    expect(lensLegend("p", false, CATALOG)).toEqual([]);
    expect(lensLegend("none", true, CATALOG)).toEqual([]);
  });
});

describe("lensOptions（レンズの選択肢）", () => {
  const paintable = new Set(["r", "d"]);
  const byId = (usedWeights: Record<string, number> | null) =>
    Object.fromEntries(lensOptions(CATALOG.axes, paintable, usedWeights, {}).map((option) => [option.id, option]));

  it("公開軸をカタログの並びのまま並べる", () => {
    expect(lensOptions(CATALOG.axes, paintable, null, {}).map((option) => option.id)).toEqual(["r", "d", "p"]);
  });

  it("生成前は未使用を付けず、生成後は使われた重みが0か無い軸だけを未使用にする", () => {
    expect(Object.values(byId(null)).some((option) => option.unused)).toBe(false);
    const after = byId({ r: 0.5, d: 0 });
    expect([after.r.unused, after.d.unused, after.p.unused]).toEqual([false, true, true]);
  });

  it("ルート確定前に塗る手段を持たない軸だけが「ルート後のみ」になる", () => {
    const options = byId(null);
    expect([options.r.routeOnly, options.d.routeOnly, options.p.routeOnly]).toEqual([false, false, true]);
  });
});
