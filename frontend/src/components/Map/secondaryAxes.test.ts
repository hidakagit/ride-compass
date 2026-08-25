// @vitest-environment node
// secondaryAxesFromCatalogAxes（改善計画T310: chip_label/proxy_hint/icon_idが軸自身の
// データから反映されることの回帰テスト）。DOM不要のためnode環境で実行する。

import { describe, expect, it } from "vitest";
import { secondaryAxesFromCatalogAxes, SECONDARY_AXES } from "./secondaryAxes";
import type { CatalogAxis } from "./axisLayers";

describe("secondaryAxesFromCatalogAxes（改善計画T310）", () => {
  it("既存軸（静的フォールバック）はchip_label/proxy_hint/icon_idが軸自身のデータから反映される", () => {
    const gradient = SECONDARY_AXES.find((axis) => axis.axisId === "gradient")!;
    expect(gradient.chipLabel).toBe("勾配");
    expect(gradient.proxyHint).toBe("（地図表示なし）標高レイヤーで確認できます");
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
    expect(axis.proxyHint).toBeUndefined();
    expect(axis.iconId).toBeUndefined();
  });

  it("chip_label/proxy_hint/icon_idが設定されていればそのまま反映される（軸スタジオ作成軸の想定）", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "gui_axis",
        display: { kind: "none", label: "GUI軸の正式名", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
        chip_label: "略称",
        proxy_hint: "代役案内",
        icon_id: "shield",
      },
    ];

    const [axis] = secondaryAxesFromCatalogAxes(catalogAxes);
    expect(axis.chipLabel).toBe("略称");
    expect(axis.proxyHint).toBe("代役案内");
    expect(axis.iconId).toBe("shield");
  });
});
