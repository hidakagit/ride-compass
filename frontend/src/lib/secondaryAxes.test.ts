// @vitest-environment node
/**
 * `secondaryAxes.ts`——軸カタログの軸から、地図のチップ・地図の見え方パネルへ出す軸の一覧を作ること。
 * 一覧から外すのは`show_map_icon`だけで、略名が無ければ地図の名前を使い、ramp軸だけが専用のレイヤーを持つ。
 *
 * 軸は架空のもの（`mapDisplay/__fixtures__/catalogAxes.ts`）。
 */
import { describe, expect, it } from "vitest";

import { catalogEntry } from "@/lib/mapDisplay/__fixtures__/catalogAxes";
import { axisMapLayerId } from "@/lib/mapDisplay/axisLayers";

import { secondaryAxesFromCatalogAxes } from "./secondaryAxes";

describe("secondaryAxesFromCatalogAxes", () => {
  it("地図のアイコンを出さない軸だけを外し、カタログの並びのまま出す", () => {
    const axes = secondaryAxesFromCatalogAxes([
      catalogEntry({ axis_id: "b" }),
      catalogEntry({ axis_id: "hidden", show_map_icon: false }),
      catalogEntry({ axis_id: "a" }),
    ]);
    expect(axes.map((axis) => axis.axisId)).toEqual(["b", "a"]);
  });

  it("略名とアイコンは軸の値を使い、略名が無ければ地図の名前を使う", () => {
    const [named, unnamed] = secondaryAxesFromCatalogAxes([
      catalogEntry({ chip_label: "略称", icon_id: "shield", display: { label: "地図の名前" } }),
      catalogEntry({ display: { label: "地図の名前" } }),
    ]);
    expect(named).toMatchObject({ chipLabel: "略称", iconId: "shield" });
    expect(unnamed).toMatchObject({ chipLabel: "地図の名前", iconId: undefined });
  });

  it("地図の表示がrampの軸だけが専用のレイヤーを持つ", () => {
    const [ramp, none] = secondaryAxesFromCatalogAxes([
      catalogEntry({ axis_id: "ramp", display: { kind: "ramp" } }),
      catalogEntry({ axis_id: "none" }),
    ]);
    expect(ramp.layerId).toBe(axisMapLayerId("ramp"));
    expect(none.layerId).toBeUndefined();
  });

  it("生値の単位・総量の単位・材料の内訳を渡す", () => {
    const [axis] = secondaryAxesFromCatalogAxes([
      catalogEntry({
        raw_value_unit: "回/km",
        raw_value_total_unit: "回",
        material_breakdown: [
          {
            material_id: "m",
            label: "材料",
            dtype: "categorical",
            unit: "",
            share: 1,
            value_labels: { x: "エックス" },
          },
        ],
      }),
    ]);
    expect(axis).toMatchObject({
      rawValueUnit: "回/km",
      rawValueTotalUnit: "回",
      materialBreakdown: [
        { materialId: "m", label: "材料", dtype: "categorical", unit: "", share: 1, valueLabels: { x: "エックス" } },
      ],
    });
  });
});
