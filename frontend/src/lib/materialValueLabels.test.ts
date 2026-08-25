// @vitest-environment node
import { describe, expect, it } from "vitest";
import { HIGHWAY_GROUPS, SURFACE_GROUPS } from "@/components/Map/roadFilterAxes";
import { materialValueLabel, MATERIAL_VALUE_LABELS } from "./materialValueLabels";

describe("materialValueLabels", () => {
  it("highway/surfaceはroadFilterAxes.tsのグルーピングから全タグ値ぶんのラベルを導出する", () => {
    for (const group of HIGHWAY_GROUPS) {
      for (const value of group.values) {
        expect(MATERIAL_VALUE_LABELS.highway[value]).toBe(group.label);
      }
    }
    for (const group of SURFACE_GROUPS) {
      for (const value of group.values) {
        expect(MATERIAL_VALUE_LABELS.surface[value]).toBe(group.label);
      }
    }
  });

  it("smoothnessはOSM標準8値ぶんの日本語ラベルを持つ", () => {
    const values = [
      "excellent",
      "good",
      "intermediate",
      "bad",
      "very_bad",
      "horrible",
      "very_horrible",
      "impassable",
    ];
    for (const value of values) {
      expect(MATERIAL_VALUE_LABELS.smoothness[value]).toBeTruthy();
    }
  });

  it("materialValueLabelは既知の値をラベルへ変換する", () => {
    expect(materialValueLabel("highway", "residential")).toBe("生活道路");
    expect(materialValueLabel("surface", "asphalt")).toBe("アスファルト");
    expect(materialValueLabel("smoothness", "good")).toBe("良好");
  });

  it("materialValueLabelは未登録の材料id・未知の値をそのまま返すフォールバック", () => {
    expect(materialValueLabel("highway", "some_new_osm_value")).toBe("some_new_osm_value");
    expect(materialValueLabel("bicycle_infra", "separated")).toBe("separated");
  });
});
