// @vitest-environment node
// secondaryAxesFromCatalogAxes（改善計画T310: chip_label/icon_idが軸自身のデータから
// 反映されること、改善計画T318: show_map_icon===falseの軸が除外されることの回帰テスト）。
// DOM不要のためnode環境で実行する。

import { describe, expect, it } from "vitest";
import { secondaryAxesFromCatalogAxes, SECONDARY_AXES } from "./secondaryAxes";
import type { CatalogAxis } from "./axisLayers";

describe("secondaryAxesFromCatalogAxes（改善計画T310）", () => {
  it("既存軸（静的フォールバック）はchip_label/icon_idが軸自身のデータから反映される", () => {
    const gradient = SECONDARY_AXES.find((axis) => axis.axisId === "gradient")!;
    expect(gradient.chipLabel).toBe("勾配");
    expect(gradient.iconId).toBe("incline");

    const carStress = SECONDARY_AXES.find((axis) => axis.axisId === "car_stress")!;
    expect(carStress.chipLabel).toBe("圧迫感");
    expect(carStress.iconId).toBe("warning-triangle");
  });

  it("chip_label未設定の軸はdisplay.labelへフォールバックする", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "no_chip_label_axis",
        display: { kind: "ramp", label: "正式名テスト", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
      },
    ];

    const [axis] = secondaryAxesFromCatalogAxes(catalogAxes);
    expect(axis.chipLabel).toBe("正式名テスト");
    expect(axis.iconId).toBeUndefined();
  });

  it("chip_label/icon_idが設定されていればそのまま反映される（軸スタジオ作成軸の想定）", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "gui_axis",
        display: { kind: "none", label: "GUI軸の正式名", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
        chip_label: "略称",
        icon_id: "shield",
      },
    ];

    const [axis] = secondaryAxesFromCatalogAxes(catalogAxes);
    expect(axis.chipLabel).toBe("略称");
    expect(axis.iconId).toBe("shield");
  });

  // 改善計画T318（ユーザー判断: 「軸スタジオで、地図マップ上にアイコン表示するかどうか
  // ON/OFFできるようにして」）。
  it("show_map_icon===falseの軸は地図上チップ・地図の見え方パネル向けの一覧から除外される", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "hidden_axis",
        display: { kind: "none", label: "非表示軸", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
        show_map_icon: false,
      },
      {
        axis_id: "shown_axis",
        display: { kind: "none", label: "表示軸", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
        show_map_icon: true,
      },
    ];

    const axes = secondaryAxesFromCatalogAxes(catalogAxes);
    expect(axes.some((axis) => axis.axisId === "hidden_axis")).toBe(false);
    expect(axes.some((axis) => axis.axisId === "shown_axis")).toBe(true);
  });

  it("show_map_icon未設定の軸は表示する扱いになる（backendが必ずtrue/falseを返すため実質常に発生しないが、型上のフォールバックとして確認）", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "unset_axis",
        display: { kind: "none", label: "未設定軸", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
      },
    ];

    const axes = secondaryAxesFromCatalogAxes(catalogAxes);
    expect(axes.some((axis) => axis.axisId === "unset_axis")).toBe(true);
  });
});
