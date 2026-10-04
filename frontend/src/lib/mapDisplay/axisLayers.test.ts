// @vitest-environment node
/**
 * `lib/mapDisplay/axisLayers.ts`——軸カタログの行を、地図が読む形（ramp軸・専用配信の軸・軸の名前の辞書）へ移すこと。
 * 入口は`rampAxesFromCatalogAxes`・`dedicatedWayValueAxesFromCatalogAxes`・`axisLabelsFromCatalogAxes`で、確かめるのは
 * 戻り値のうち地図の表示の項目。軸は`testing/catalogAxes.ts`の雛形で組む（実際の公開軸を使わない）。
 *
 * ここで見ないもの:
 * - 名前・略名・単位など軸に共通の項目を行から移すこと → `lib/catalogAxis.test.ts`
 * - 移した軸で道を塗る式・段 → `features/map/scene/groups/axisLines.test.ts`・`valueScale.test.ts`
 * - 地図のレイヤーの鍵（`axisMapLayerId`）→ 文字列の組み立てだけで、レイヤーの登録と可視の切り替えのテストが通す
 */
import { describe, expect, it } from "vitest";

import { catalogEntry, dedicatedEntry, rampEntry, tileInput } from "@/testing/catalogAxes";

import { axisLabelsFromCatalogAxes, dedicatedWayValueAxesFromCatalogAxes, rampAxesFromCatalogAxes } from "./axisLayers";

describe("rampAxesFromCatalogAxes", () => {
  it("地図の表示がrampの軸だけを、カタログの順に残す", () => {
    const axes = [
      rampEntry("ramp_b", [1]),
      catalogEntry({ axis_id: "not_on_map" }),
      dedicatedEntry("dedicated", [1]),
      rampEntry("ramp_a", [1]),
    ];

    expect(rampAxesFromCatalogAxes(axes, {}).map((axis) => axis.axisId)).toEqual(["ramp_b", "ramp_a"]);
  });

  it("地図の分類・段の境界・体感ラベルを表示の宣言から移し、体感ラベルが無ければ持たない", () => {
    const [labelled, plain] = rampAxesFromCatalogAxes(
      [rampEntry("labelled", [10, 20], { display_band_labels_override: ["低", "中", "高"] }), rampEntry("plain", [5])],
      {},
    );

    expect(labelled).toMatchObject({
      category: "roadCondition",
      thresholds: [10, 20],
      bandLabelsOverride: ["低", "中", "高"],
    });
    expect(plain.bandLabelsOverride).toBeUndefined();
  });

  it("タイルの入力を、材料の型ごとの項目ごと移し、宣言の無い分類表・折れ点は持たない", () => {
    const entry = rampEntry("a", [1], {
      display: {
        kind: "ramp",
        label: "a",
        category: "roadCondition",
        thresholds: [1],
        tile_inputs: [
          tileInput({ property: "num", weight: 2 }),
          tileInput({ property: "flag", boolean: true, true_value: 3, false_value: 1, has_unknown_fallback: true }),
          tileInput({ property: "kind", weight: 1, categories: { x: 0.5 } }),
          tileInput({
            property: "speed",
            weight: 1,
            breakpoints: [
              [0, 0],
              [60, 1],
            ],
          }),
        ],
      },
    });

    expect(rampAxesFromCatalogAxes([entry], {})[0].tileInputs).toEqual([
      { property: "num", weight: 2, boolean: false, trueValue: 0, falseValue: 0, hasUnknownFallback: false },
      { property: "flag", weight: 0, boolean: true, trueValue: 3, falseValue: 1, hasUnknownFallback: true },
      {
        property: "kind",
        weight: 1,
        boolean: false,
        trueValue: 0,
        falseValue: 0,
        hasUnknownFallback: false,
        categories: { x: 0.5 },
      },
      {
        property: "speed",
        weight: 1,
        boolean: false,
        trueValue: 0,
        falseValue: 0,
        hasUnknownFallback: false,
        breakpoints: [
          [0, 0],
          [60, 1],
        ],
      },
    ]);
  });

  it("実行時の係数が要る入力は、届いた係数を重みへ掛け、届いていなければ寄与0で塗らず「不明」の印を付ける", () => {
    const entry = rampEntry("a", [1], {
      display: {
        kind: "ramp",
        label: "a",
        category: "roadCondition",
        thresholds: [1],
        tile_inputs: [
          tileInput({ property: "scaled", weight: 2, needs_runtime_scale: true }),
          tileInput({ property: "zero_scaled", weight: 2, needs_runtime_scale: true }),
          tileInput({ property: "unscaled", weight: 2, needs_runtime_scale: true }),
          tileInput({ property: "plain", weight: 2 }),
        ],
      },
    });

    const inputs = rampAxesFromCatalogAxes([entry], { scaled: 0.25, zero_scaled: 0, plain: 10 })[0].tileInputs;

    expect(inputs.map(({ property, weight, scaleMissing }) => ({ property, weight, scaleMissing }))).toEqual([
      { property: "scaled", weight: 0.5, scaleMissing: undefined },
      { property: "zero_scaled", weight: 0, scaleMissing: undefined },
      { property: "unscaled", weight: 0, scaleMissing: true },
      { property: "plain", weight: 2, scaleMissing: undefined },
    ]);
  });
});

describe("dedicatedWayValueAxesFromCatalogAxes", () => {
  it("専用配信を持つ軸だけを、カタログの順に残す", () => {
    const axes = [dedicatedEntry("d_b", [1]), rampEntry("ramp", [1]), dedicatedEntry("d_a", [1])];

    expect(dedicatedWayValueAxesFromCatalogAxes(axes).map((axis) => axis.axisId)).toEqual(["d_b", "d_a"]);
  });

  it("配信に添える入力（時刻・方位・速度）の要否を、軸ごとにカタログの条件の名前から移す", () => {
    const [timeOnly, bearingAndSpeed] = dedicatedWayValueAxesFromCatalogAxes([
      dedicatedEntry("time_only", [1], { dynamic_way_value_conditions: ["at"] }),
      dedicatedEntry("bearing_speed", [1], { dynamic_way_value_conditions: ["bearing_deg", "speed_kmh"] }),
    ]);

    expect(timeOnly).toMatchObject({ needsTime: true, needsBearing: false, needsSpeed: false });
    expect(bearingAndSpeed).toMatchObject({ needsTime: false, needsBearing: true, needsSpeed: true });
  });

  it("塗るときの表示の宣言（値の種類・境界・凡例の目盛り・体感ラベル）を同じ行から作り、宣言の無い体感ラベルは持たない", () => {
    const [declared, bare] = dedicatedWayValueAxesFromCatalogAxes([
      dedicatedEntry("declared", [-2, 2], {
        map_value: { kind: "signed_material", material: "m" },
        map_legend: { boundaries: [-2, 2], unit: "%" },
        display_band_labels_override: ["下り", "平坦", "上り"],
      }),
      dedicatedEntry("bare", [33, 66]),
    ]);

    expect(declared.display).toEqual({
      kind: "signed_material",
      boundaries: [-2, 2],
      legend: { boundaries: [-2, 2], unit: "%" },
      bandLabels: ["下り", "平坦", "上り"],
    });
    expect(bare.display).toEqual({
      kind: "difficulty",
      boundaries: [33, 66],
      legend: { boundaries: [33, 66], unit: null },
      bandLabels: undefined,
    });
  });
});

describe("axisLabelsFromCatalogAxes", () => {
  it("地図に出ない軸も含めた全軸を、地図の表示名ではなく軸の名前で引ける", () => {
    const labels = axisLabelsFromCatalogAxes([
      rampEntry("on_map", [1], { label: "地図に出る軸" }),
      catalogEntry({ axis_id: "off_map", label: "地図に出ない軸" }),
    ]);

    expect(labels).toEqual({ on_map: "地図に出る軸", off_map: "地図に出ない軸" });
  });
});
