// @vitest-environment node
// secondaryAxesFromCatalogAxes（改善計画T310: chip_label/icon_idが軸自身のデータから
// 反映されること、改善計画T318: show_map_icon===falseの軸が除外されることの回帰テスト）。
// DOM不要のためnode環境で実行する。

import { describe, expect, it } from "vitest";
import { secondaryAxesFromCatalogAxes } from "./secondaryAxes";
import type { CatalogAxis } from "./axisLayers";

describe("secondaryAxesFromCatalogAxes（改善計画T310）", () => {
  it("chip_label未設定の軸はdisplay.labelへフォールバックする", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "no_chip_label_axis",
        label: "正式名テスト",
        display: {
          kind: "ramp",
          label: "正式名テスト",
          category: "trafficSafety",
          tile_inputs: [],
          thresholds: [],
          unit: "",
          note: "",
        },
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
        display: {
          kind: "none",
          label: "GUI軸の正式名",
          category: "trafficSafety",
          tile_inputs: [],
          thresholds: [],
          unit: "",
          note: "",
        },
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
        display: {
          kind: "none",
          label: "非表示軸",
          category: "trafficSafety",
          tile_inputs: [],
          thresholds: [],
          unit: "",
          note: "",
        },
        show_map_icon: false,
      },
      {
        axis_id: "shown_axis",
        label: "表示軸",
        display: {
          kind: "none",
          label: "表示軸",
          category: "trafficSafety",
          tile_inputs: [],
          thresholds: [],
          unit: "",
          note: "",
        },
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
        display: {
          kind: "none",
          label: "未設定軸",
          category: "trafficSafety",
          tile_inputs: [],
          thresholds: [],
          unit: "",
          note: "",
        },
      },
    ];

    const axes = secondaryAxesFromCatalogAxes(catalogAxes);
    expect(axes.some((axis) => axis.axisId === "unset_axis")).toBe(true);
  });

  // 地図向けの一覧から軸を外す唯一のスイッチは`show_map_icon`（軸スタジオから設定する）。
  // 軸id・categoryをコード側で名指しする除外を足すと、軸スタジオ側で値が変わった時点で
  // 黙って効かなくなるため、除外の経路はこれ1本に保つ。
  describe("show_map_icon による除外", () => {
    it("show_map_icon===falseの軸は一覧から落ちる", () => {
      const catalogAxes: CatalogAxis[] = [
        {
          axis_id: "hidden_axis",
          label: "地図に出さない軸",
          show_map_icon: false,
          display: {
            kind: "ramp",
            label: "地図に出さない軸",
            category: "roadCondition",
            tile_inputs: [],
            thresholds: [],
            unit: "",
            note: "",
          },
        },
        {
          axis_id: "axis_sample",
          label: "見本の軸",
          display: {
            kind: "ramp",
            label: "見本の軸",
            category: "trafficSafety",
            tile_inputs: [],
            thresholds: [],
            unit: "",
            note: "",
          },
        },
      ];

      const axes = secondaryAxesFromCatalogAxes(catalogAxes);
      expect(axes.map((axis) => axis.axisId)).toEqual(["axis_sample"]);
    });

    it("displayを持たない軸（非公開）は一覧から落ちる", () => {
      const catalogAxes: CatalogAxis[] = [
        {
          axis_id: "unpublished_axis",
          label: "非公開軸",
          display: null,
        },
        {
          axis_id: "axis_sample",
          label: "見本の軸",
          display: {
            kind: "ramp",
            label: "見本の軸",
            category: "trafficSafety",
            tile_inputs: [],
            thresholds: [],
            unit: "",
            note: "",
          },
        },
      ];

      const axes = secondaryAxesFromCatalogAxes(catalogAxes);
      expect(axes.map((axis) => axis.axisId)).toEqual(["axis_sample"]);
    });
  });
});
