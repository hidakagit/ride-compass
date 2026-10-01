// @vitest-environment node
/**
 * `axisLayers.ts`——軸カタログの軸から、タイルの材料で塗るramp軸と軸の名前の辞書を作ること。
 *
 * 軸は架空のもの（`testing/catalogAxes.ts`）。
 */
import { describe, expect, it } from "vitest";

import { catalogAxisFromEntry } from "@/lib/catalogAxis";

import { catalogEntry, tileInput } from "@/testing/catalogAxes";
import { axisLabelsFromCatalogAxes, rampAxesFromCatalogAxes } from "./axisLayers";

describe("rampAxesFromCatalogAxes", () => {
  it("地図の表示がrampの軸だけを、軸の共通の項目にタイルの入力・境界・段の名前を足して移す", () => {
    const ramp = catalogEntry({
      axis_id: "ramp",
      label: "軸の名前",
      raw_value_unit: "件/km",
      display_band_labels_override: ["少", "多"],
      display: {
        kind: "ramp",
        category: "trafficSafety",
        tile_inputs: [
          tileInput({ property: "a", weight: 0.5, categories: { x: 1 } }),
          tileInput({ property: "b", weight: 1 }),
        ],
        thresholds: [10],
      },
    });
    const [axis, ...rest] = rampAxesFromCatalogAxes([ramp, catalogEntry({ axis_id: "none" })]);
    expect(rest).toEqual([]);
    expect(axis).toEqual({
      ...catalogAxisFromEntry(ramp),
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
      bandLabelsOverride: ["少", "多"],
    });
  });

  // 係数が届いていないときの塗り方は、凡例の段への当てはまりで見る（`features/map/view/lens.test.ts`）。
  it("実行時の係数が要る入力は重みへ係数を掛け、要らない入力は変えない", () => {
    const axis = catalogEntry({
      display: {
        kind: "ramp",
        tile_inputs: [
          tileInput({ property: "scaled", weight: 1, needs_runtime_scale: true }),
          tileInput({ property: "plain", weight: 2 }),
        ],
      },
    });
    const weights = (scales: Record<string, number>) =>
      rampAxesFromCatalogAxes([axis], scales)[0].tileInputs.map((input) => input.weight);
    expect(weights({ scaled: 1 / 3, plain: 5 })).toEqual([1 / 3, 2]);
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
