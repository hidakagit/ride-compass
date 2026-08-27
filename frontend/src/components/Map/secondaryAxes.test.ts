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
        label: "正式名テスト",
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
        label: "GUI軸の正式名",
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
        label: "非表示軸",
        display: { kind: "none", label: "非表示軸", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
        show_map_icon: false,
      },
      {
        axis_id: "shown_axis",
        label: "表示軸",
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
        label: "未設定軸",
        display: { kind: "none", label: "未設定軸", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
      },
    ];

    const axes = secondaryAxesFromCatalogAxes(catalogAxes);
    expect(axes.some((axis) => axis.axisId === "unset_axis")).toBe(true);
  });

  // コードレビュー指摘の修正（secondaryAxes.tsのコメント参照）: T308でaxis_display_for()が
  // 全公開軸に対して常に非nullを返すようになった結果、`display !== null`だけのフィルタでは
  // category="動的"（wind等、複数材料から合成した推定指標ではなく生の外部データそのもの）を
  // 除外できなくなっていた不具合の回帰テスト。
  describe("「動的」軸除外フィルタ（コードレビュー指摘の修正）", () => {
    it("category=動的の軸は推定指標グループの一覧から除外される", () => {
      const catalogAxes: CatalogAxis[] = [
        {
          axis_id: "wind",
          label: "風",
          category: "動的",
          display: { kind: "none", label: "風", category: "weather", tile_inputs: [], thresholds: [], unit: "", note: "" },
        },
        {
          axis_id: "gradient",
          label: "勾配",
          category: "推定",
          display: { kind: "none", label: "勾配", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
        },
      ];

      const axes = secondaryAxesFromCatalogAxes(catalogAxes);
      expect(axes.some((axis) => axis.axisId === "wind")).toBe(false);
      expect(axes.some((axis) => axis.axisId === "gradient")).toBe(true);
    });

    it("既存軸（静的フォールバック）にはcategory=動的の軸が含まれない（windは推定指標チップグループに出ない）", () => {
      expect(SECONDARY_AXES.some((axis) => axis.axisId === "wind")).toBe(false);
    });

    it("category=動的以外の軸はdisplay!==nullかつshow_map_icon!==falseであれば除外されない", () => {
      const catalogAxes: CatalogAxis[] = [
        {
          axis_id: "car_stress",
          label: "車の圧迫感",
          display: { kind: "ramp", label: "車の圧迫感", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
        },
      ];

      const axes = secondaryAxesFromCatalogAxes(catalogAxes);
      expect(axes.some((axis) => axis.axisId === "car_stress")).toBe(true);
    });
  });
});
