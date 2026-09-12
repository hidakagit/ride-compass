// @vitest-environment node
// secondaryAxesFromCatalogAxes（改善計画T310: chip_label/icon_idが軸自身のデータから
// 反映されること、改善計画T318: show_map_icon===falseの軸が除外されることの回帰テスト）。
// DOM不要のためnode環境で実行する。

import { describe, expect, it } from "vitest";
import { secondaryAxesFromCatalogAxes, SECONDARY_AXES } from "./secondaryAxes";
import type { CatalogAxis } from "./axisLayers";
import axisCatalog from "@/types/generated/axis-catalog.json";

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

  // 改善計画T443: display_thresholds_overrideが軸自身のデータからそのまま反映されることの
  // 回帰テスト（page.tsx: gradientBoundaries→MapView.tsxのプレルート表示配線の唯一のデータ源）。
  it("display_thresholds_overrideが設定されていればそのまま反映され、未設定はundefinedになる", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "gradient",
        label: "勾配",
        display: { kind: "none", label: "勾配", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
        display_thresholds_override: [-2, 2, 6, 10],
      },
      {
        axis_id: "no_override_axis",
        label: "上書き無し軸",
        display: { kind: "none", label: "上書き無し軸", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
        display_thresholds_override: null,
      },
    ];

    const axes = secondaryAxesFromCatalogAxes(catalogAxes);
    expect(axes.find((axis) => axis.axisId === "gradient")?.displayThresholdsOverride).toEqual([-2, 2, 6, 10]);
    expect(axes.find((axis) => axis.axisId === "no_override_axis")?.displayThresholdsOverride).toBeUndefined();
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

  // 地図向けの一覧から軸を外す唯一のスイッチは`show_map_icon`（軸スタジオから設定する）。
  // 軸id・categoryをコード側で名指しする除外を足すと、軸スタジオ側で値が変わった時点で
  // 黙って効かなくなるため、除外の経路はこれ1本に保つ。
  describe("show_map_icon による除外（実データ）", () => {
    it("show_map_icon===falseの既存軸は一覧から落ち、それ以外の表示可能な軸は残る", () => {
      const catalogAxes = axisCatalog.axes as CatalogAxis[];
      const hidden = catalogAxes.filter((axis) => axis.show_map_icon === false);
      const shown = catalogAxes.filter((axis) => axis.display !== null && axis.show_map_icon !== false);
      // 母集団が空だとこのテストは何も確かめずに緑になる。どちらかが0件になったら
      // 「除外が効いている」の確認が消えた合図なので、フィクスチャではなく実データ側を見直す。
      expect(hidden.length).toBeGreaterThan(0);
      expect(shown.length).toBeGreaterThan(0);
      for (const axis of hidden) {
        expect(SECONDARY_AXES.some((entry) => entry.axisId === axis.axis_id)).toBe(false);
      }
      for (const axis of shown) {
        expect(SECONDARY_AXES.some((entry) => entry.axisId === axis.axis_id)).toBe(true);
      }
    });

    it("displayを持たない軸（非公開）は一覧から落ちる", () => {
      const catalogAxes: CatalogAxis[] = [
        {
          axis_id: "unpublished_axis",
          label: "非公開軸",
          display: null,
        },
        {
          axis_id: "car_stress",
          label: "車の圧迫感",
          display: { kind: "ramp", label: "車の圧迫感", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
        },
      ];

      const axes = secondaryAxesFromCatalogAxes(catalogAxes);
      expect(axes.map((axis) => axis.axisId)).toEqual(["car_stress"]);
    });
  });
});
