// @vitest-environment node
// `lens.ts`——レンズの1つの値から、全道路を塗る軸・凡例・選択肢を導く。
//
// ここで見ないもの:
// - 凡例の段の境界・ラベルの規則そのもの → `mapColorLegend.test.ts`
import { describe, expect, it } from "vitest";

import { catalogOf, catalogEntry, dedicatedEntry, rampEntry } from "@/features/map/view/__fixtures__/catalog";
import { rampAxesFromCatalogAxes } from "@/lib/mapDisplay/axisLayers";
import { catalogAxis } from "@/lib/mapDisplay/__fixtures__/catalogAxes";
import type { DedicatedWayValueDisplay } from "@/lib/mapDisplay/dedicatedWayValueLayer";
import { LEGEND_NO_DATA_KEY } from "@/lib/mapDisplay/mapColorLegend";
import { bandColorsFor, COLOR_NO_DATA } from "@/lib/mapDisplay/valueScale";
import type { RampAxis } from "@/lib/mapDisplay/axisLayers";
import { lensLegend, lensOptions, paintedAxisId } from "./lens";

// 凡例はレンズの入口（`lensLegend`）から引く。ルート確定前・その軸だけを持つカタログで引けば、
// ramp軸・専用配信軸それぞれの凡例そのものになる。
function rampLegend(axis: RampAxis) {
  return lensLegend(axis.axisId, false, { routeStyleModes: [], rampAxes: [axis], dedicatedAxes: [] });
}
function dedicatedWayValueLegend(display: DedicatedWayValueDisplay) {
  const axis = { axisId: "d", label: "d", needsTime: false, needsBearing: false, needsSpeed: false, display };
  return lensLegend("d", false, { routeStyleModes: [], rampAxes: [], dedicatedAxes: [axis] });
}

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

describe("ramp軸の凡例の単位", () => {
  const rampDisplay = { tile_inputs: [{ property: "v", weight: 1 }], thresholds: [1, 2] };

  it("軸カタログのraw_value_unitを段階ラベルへ添える", () => {
    const [axis] = rampAxesFromCatalogAxes([catalogAxis({ raw_value_unit: "回/km", display: rampDisplay })]);

    expect(rampLegend(axis).map((band) => band.label)).toEqual(["1回/km未満", "1〜2回/km", "2回/km以上"]);
  });

  it("単位が定まらない軸（raw_value_unitがnull）は数値だけの段階ラベルになる", () => {
    const [axis] = rampAxesFromCatalogAxes([catalogAxis({ raw_value_unit: null, display: rampDisplay })]);

    expect(rampLegend(axis).map((band) => band.label)).toEqual(["1未満", "1〜2", "2以上"]);
  });
});

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
