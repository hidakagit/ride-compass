// @vitest-environment node
/**
 * `lib/catalogAxis.ts`——軸カタログの1行を、画面が読む形（`CatalogAxis`）へ移す。
 *
 * 軸は`testing/catalogAxes.ts`の雛形で組む（実際の公開軸を入力に使わない）。同じ型の項目どうし（名前と説明、
 * 生値の単位と総量の単位等）には互いに違う値を入れ、取り違えて移すと落ちるようにする。
 *
 * ここで見ないもの:
 * - 移した項目を用途ごとに足した型（地図のチップ・ramp軸・専用配信の軸）→ `features/map/secondaryAxes.test.ts`・
 *   `lib/mapDisplay/axisLayers.test.ts`
 * - 移した項目をどう描くか → 使う部品（`components/AxisContributionBar`等）
 */
import { describe, expect, it } from "vitest";

import { catalogEntry } from "@/testing/catalogAxes";
import { catalogAxisFromEntry } from "@/lib/catalogAxis";

describe("catalogAxisFromEntry", () => {
  it("行の項目を、画面が読む名前の項目へ取り違えずに移す", () => {
    const entry = catalogEntry({
      axis_id: "axis_a",
      label: "軸Aの名前",
      chip_label: "軸A",
      description: "軸Aの説明",
      icon_id: "icon_a",
      panel_hint: "軸Aの詳しい説明",
      dedicated_way_value_layer: true,
      map_value: { kind: "signed_material", material: "num_a" },
      map_value_unit: "地図の単位",
      raw_value_unit: "生値の単位",
      raw_value_total_unit: "総量の単位",
      material_breakdown: [
        { material_id: "num_a", label: "数値A", dtype: "numeric", unit: "m", share: 0.75, value_labels: {} },
        {
          material_id: "cat_a",
          label: "分類A",
          dtype: "categorical",
          unit: "",
          share: 0.25,
          value_labels: { x: "エックス" },
        },
      ],
      primary_attribute_ids: ["attr_a", "attr_b"],
      weather_layer_groups: ["weather_a"],
    });

    expect(catalogAxisFromEntry(entry)).toEqual({
      axisId: "axis_a",
      label: "軸Aの名前",
      chipLabel: "軸A",
      description: "軸Aの説明",
      iconId: "icon_a",
      panelHint: "軸Aの詳しい説明",
      dedicatedWayValueLayer: true,
      mapValueKind: "signed_material",
      mapValueUnit: "地図の単位",
      rawValueUnit: "生値の単位",
      rawValueTotalUnit: "総量の単位",
      materialBreakdown: [
        { materialId: "num_a", label: "数値A", dtype: "numeric", unit: "m", share: 0.75, valueLabels: {} },
        {
          materialId: "cat_a",
          label: "分類A",
          dtype: "categorical",
          unit: "",
          share: 0.25,
          valueLabels: { x: "エックス" },
        },
      ],
      primaryAttributeIds: ["attr_a", "attr_b"],
      weatherLayerGroups: ["weather_a"],
    });
  });

  it("略名・アイコン・詳しい説明が無い軸は、略名に名前を使い、アイコンと詳しい説明を持たない", () => {
    const axis = catalogAxisFromEntry(
      catalogEntry({ axis_id: "axis_a", label: "軸Aの名前", chip_label: null, icon_id: null, panel_hint: null }),
    );

    expect(axis.chipLabel).toBe("軸Aの名前");
    expect(axis.iconId).toBeUndefined();
    expect(axis.panelHint).toBeUndefined();
  });
});
