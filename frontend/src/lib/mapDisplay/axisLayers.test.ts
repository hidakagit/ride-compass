// @vitest-environment node
/**
 * `axisLayers.ts`——軸カタログの軸から、タイルの材料で塗るramp軸と軸の名前の辞書を作り、段の数によらない緑→赤の
 * 配色を出すこと。
 *
 * 軸は架空のもの（`__fixtures__/catalogAxes.ts`）。配色のアンカーの値はbackendの宣言（生成物）なので書き写さない。
 */
import { describe, expect, it } from "vitest";

import { catalogEntry, tileInput } from "./__fixtures__/catalogAxes";
import { axisLabelsFromCatalogAxes, rampAxesFromCatalogAxes, rampColorForBand } from "./axisLayers";

describe("rampColorForBand", () => {
  it("両端は段の数によらず同じ色で、段が1つなら低い側の色。どれも#rrggbb", () => {
    const [low, high] = [rampColorForBand(0, 4), rampColorForBand(3, 4)];
    for (const bandCount of [2, 3, 5, 6]) {
      expect(rampColorForBand(0, bandCount)).toBe(low);
      expect(rampColorForBand(bandCount - 1, bandCount)).toBe(high);
      expect(rampColorForBand(1, bandCount)).toMatch(/^#[0-9a-f]{6}$/);
    }
    expect(rampColorForBand(0, 1)).toBe(low);
  });
});

describe("rampAxesFromCatalogAxes", () => {
  it("地図の表示がrampの軸だけを、タイルの入力・境界・単位・地図のチップの表示と一緒に移す", () => {
    const ramp = catalogEntry({
      axis_id: "ramp",
      raw_value_unit: "件/km",
      panel_hint: "説明",
      icon_id: "incline",
      chip_label: "略",
      display_band_labels_override: ["少", "多"],
      display: {
        kind: "ramp",
        label: "地図の名前",
        category: "trafficSafety",
        tile_inputs: [tileInput({ property: "a", weight: 0.5, categories: { x: 1 } }), tileInput({ property: "b" })],
        thresholds: [10],
      },
    });
    const [axis, ...rest] = rampAxesFromCatalogAxes([ramp, catalogEntry({ axis_id: "none" })]);
    expect(rest).toEqual([]);
    expect(axis).toEqual({
      axisId: "ramp",
      label: "地図の名前",
      category: "trafficSafety",
      tileInputs: [
        {
          property: "a",
          weight: 0.5,
          boolean: false,
          trueValue: 0,
          falseValue: 0,
          hasUnknownFallback: false,
          categories: { x: 1 },
          breakpoints: undefined,
        },
        {
          property: "b",
          weight: 1,
          boolean: false,
          trueValue: 0,
          falseValue: 0,
          hasUnknownFallback: false,
          categories: undefined,
          breakpoints: undefined,
        },
      ],
      thresholds: [10],
      unit: "件/km",
      panelHint: "説明",
      iconId: "incline",
      chipLabel: "略",
      bandLabelsOverride: ["少", "多"],
    });
  });

  it("地図のチップの表示が無い軸は未設定のまま渡す（呼び出し側の既定に任せる）", () => {
    const [axis] = rampAxesFromCatalogAxes([catalogEntry({ display: { kind: "ramp" } })]);
    expect(axis).toMatchObject({ unit: "", panelHint: undefined, iconId: undefined, chipLabel: undefined });
  });

  it("実行時の係数が要る入力は重みへ係数を掛け、係数が届いていなければ寄与を0にする。要らない入力は変えない", () => {
    const axis = catalogEntry({
      display: {
        kind: "ramp",
        tile_inputs: [
          tileInput({ property: "scaled", needs_runtime_scale: true }),
          tileInput({ property: "plain", weight: 2 }),
        ],
      },
    });
    const weights = (scales: Record<string, number>) =>
      rampAxesFromCatalogAxes([axis], scales)[0].tileInputs.map((input) => input.weight);
    expect(weights({ scaled: 1 / 3, plain: 5 })).toEqual([1 / 3, 2]);
    expect(weights({})).toEqual([0, 2]);
  });
});

describe("axisLabelsFromCatalogAxes", () => {
  it("地図に出ない軸も含め、軸の名前（地図の名前でも軸idでもない）を引ける", () => {
    const labels = axisLabelsFromCatalogAxes([
      catalogEntry({ axis_id: "internal_name", label: "軸の名前", display: { kind: "ramp", label: "地図の名前" } }),
      catalogEntry({ axis_id: "none_axis", label: "地図に出ない軸" }),
    ]);
    expect(labels).toEqual({ internal_name: "軸の名前", none_axis: "地図に出ない軸" });
  });
});
