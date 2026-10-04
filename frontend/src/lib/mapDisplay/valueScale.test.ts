// @vitest-environment node
/**
 * `lib/mapDisplay/valueScale.ts`——地図が軸を塗る段の並び（下限・鍵・範囲の文字・体感ラベル・色）と、値の種類ごとの配色。
 * 入口は`bandColorsFor`・`valueBands`・`rampAxisBands`・`dedicatedAxisBands`で、確かめるのは戻り値。配色の中継点は
 * 生成物の`palette.json`から引く（色の値はbackendの宣言が持ち、ここは並べ方を見る）。
 *
 * ここで見ないもの:
 * - 範囲の文字・鍵の書き方と、体感ラベルを添える条件 → `mapColorLegend.test.ts`
 * - 段で道・ルートの線を塗る式 → `routeStyleModes.test.ts`・`features/map/scene/groups/axisLines.test.ts`
 * - 中継点の間の色の見え方（濁らないこと）→ 数の性質として書けず、管理画面の段のプレビューで見る
 */
import { describe, expect, it } from "vitest";

import { dedicatedEntry, rampEntry } from "@/testing/catalogAxes";
import palette from "@/types/generated/palette.json";

import { dedicatedWayValueAxesFromCatalogAxes, rampAxesFromCatalogAxes } from "./axisLayers";
import { bandColorsFor, dedicatedAxisBands, rampAxisBands, valueBands } from "./valueScale";

const {
  evaluation_good: GOOD,
  evaluation_mid: MID,
  evaluation_bad: BAD,
  evaluation_extreme: EXTREME,
  signed_descent: DESCENT,
} = palette.semantic;

/** 境界`n`本（段は`n+1`）。値そのものは配色に効かない。 */
const boundaries = (n: number) => Array.from({ length: n }, (_, i) => i * 10);

describe("難易度の配色", () => {
  it("段は境界の数＋1で、易しい色から始まり最も難しい色で終わる", () => {
    for (const n of [1, 2, 5, 9]) {
      const colors = bandColorsFor("difficulty", boundaries(n));
      expect(colors).toHaveLength(n + 1);
      expect(colors[0]).toBe(GOOD);
      expect(colors[n]).toBe(EXTREME);
    }
  });

  it("中継点は段の上へ均等に置かれ、段が中継点と同じ数なら中継点そのものを並べる", () => {
    expect(bandColorsFor("difficulty", boundaries(3))).toEqual([GOOD, MID, BAD, EXTREME]);
    const seven = bandColorsFor("difficulty", boundaries(6));
    expect([seven[0], seven[2], seven[4], seven[6]]).toEqual([GOOD, MID, BAD, EXTREME]);
  });

  it("段を増やしても、隣り合う段は違う色になる", () => {
    const colors = bandColorsFor("difficulty", boundaries(11));

    colors.slice(1).forEach((color, i) => expect(color, `段${i}と段${i + 1}`).not.toBe(colors[i]));
  });

  it("境界が無ければ、易しい色の段1つになる", () => {
    expect(bandColorsFor("difficulty", [])).toEqual([GOOD]);
  });
});

describe("符号付き材料の配色（0を境に分ける）", () => {
  it("0を含む段を平坦（難易度の易しい色）にし、下は下りの色から、上は難易度の配色で最も難しい色まで塗る", () => {
    expect(bandColorsFor("signed_material", [-2, 2])).toEqual([DESCENT, GOOD, EXTREME]);

    const colors = bandColorsFor("signed_material", [-6, -2, 2, 6]);
    expect(colors).toHaveLength(5);
    expect(colors[0]).toBe(DESCENT);
    expect(colors[2]).toBe(GOOD);
    expect(colors[4]).toBe(EXTREME);
    expect(new Set(colors).size).toBe(5);
  });

  it("境界がちょうど0なら、0から始まる段を平坦にする", () => {
    expect(bandColorsFor("signed_material", [-2, 0, 2])).toEqual([DESCENT, expect.any(String), GOOD, EXTREME]);
  });

  it("境界がすべて0以下なら最上段を、すべて正なら最下段を平坦にする", () => {
    const allNonPositive = bandColorsFor("signed_material", [-4, -2, 0]);
    expect(allNonPositive.at(-1)).toBe(GOOD);
    expect(allNonPositive[0]).toBe(DESCENT);

    expect(bandColorsFor("signed_material", [2, 4])).toEqual([GOOD, expect.any(String), EXTREME]);
    expect(bandColorsFor("signed_material", [2, 4])).not.toContain(DESCENT);
  });
});

describe("valueBands", () => {
  it("段ごとに下限（最下段は-∞）を持ち、色は値の種類の配色に従う", () => {
    const bands = valueBands("signed_material", [-2, 2], { boundaries: [-2, 2], unit: "%" }, undefined);

    expect(bands.map(({ lowerBound, color, label }) => ({ lowerBound, color, label }))).toEqual([
      { lowerBound: Number.NEGATIVE_INFINITY, color: DESCENT, label: "-2%未満" },
      { lowerBound: -2, color: GOOD, label: "-2〜2%" },
      { lowerBound: 2, color: EXTREME, label: "2%以上" },
    ]);
  });

  it("得点で書く段は点を添え、体感ラベルは段の数と合うときだけ添える（無ければ影響の点と名乗る）", () => {
    const score = { boundaries: [33], unit: null };
    expect(valueBands("difficulty", [33], score, ["低", "高"]).map((band) => band.label)).toEqual([
      "低[33点未満]",
      "高[33点以上]",
    ]);
    expect(valueBands("difficulty", [33], score, ["低", "中", "高"]).map((band) => band.label)).toEqual([
      "影響 33点未満",
      "影響 33点以上",
    ]);
  });

  it("塗る境界と書く境界が違う軸は、範囲を書く境界の量で名乗り、下限は塗る境界", () => {
    const bands = valueBands("difficulty", [30, 70], { boundaries: [5, 20], unit: "mm" }, undefined);

    expect(bands.map(({ lowerBound, label }) => ({ lowerBound, label }))).toEqual([
      { lowerBound: Number.NEGATIVE_INFINITY, label: "5mm未満" },
      { lowerBound: 30, label: "5〜20mm" },
      { lowerBound: 70, label: "20mm以上" },
    ]);
  });
});

describe("rampAxisBands", () => {
  it("軸の地図表示の境界で切り、凡例の目盛りの単位と体感ラベルを添える", () => {
    const [axis] = rampAxesFromCatalogAxes(
      [
        rampEntry("a", [10, 20], {
          map_legend: { boundaries: [10, 20], unit: "台/日" },
          display_band_labels_override: ["少", "中", "多"],
        }),
      ],
      {},
    );

    expect(rampAxisBands(axis).map(({ lowerBound, label }) => ({ lowerBound, label }))).toEqual([
      { lowerBound: Number.NEGATIVE_INFINITY, label: "少[10台/日未満]" },
      { lowerBound: 10, label: "中[10〜20台/日]" },
      { lowerBound: 20, label: "多[20台/日以上]" },
    ]);
  });

  it("量で書けない軸は、塗る境界で切り、ルート後の線と同じ得点で名乗る", () => {
    const [axis] = rampAxesFromCatalogAxes(
      [rampEntry("a", [-25], { map_legend: { boundaries: [25], unit: null } })],
      {},
    );

    expect(rampAxisBands(axis).map(({ lowerBound, label }) => ({ lowerBound, label }))).toEqual([
      { lowerBound: Number.NEGATIVE_INFINITY, label: "影響 25点未満" },
      { lowerBound: -25, label: "影響 25点以上" },
    ]);
  });
});

describe("dedicatedAxisBands", () => {
  it("宣言した境界・値の種類・単位・体感ラベルで段を作る", () => {
    const [axis] = dedicatedWayValueAxesFromCatalogAxes([
      dedicatedEntry("a", [-2, 2], {
        map_value: { kind: "signed_material", material: "m" },
        map_legend: { boundaries: [-2, 2], unit: "%" },
        display_band_labels_override: ["下り", "平坦", "上り"],
      }),
    ]);

    expect(dedicatedAxisBands(axis.display).map(({ color, label }) => ({ color, label }))).toEqual([
      { color: DESCENT, label: "下り[-2%未満]" },
      { color: GOOD, label: "平坦[-2〜2%]" },
      { color: EXTREME, label: "上り[2%以上]" },
    ]);
  });
});
