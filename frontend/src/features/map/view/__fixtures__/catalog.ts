// 地図の見え方のテストが使う軸カタログ。**実際の公開軸を使わない**——軸の集合はDBが持ち、
// 軸スタジオで増減する。見たい性質（ramp表示を持つ・専用配信を持つ・どちらも持たない）だけを
// 架空の軸へ持たせ、導出は本番と同じ`axisCatalogFromResponse`を通す。
import { axisCatalogFromResponse, type AxisCatalog } from "@/lib/axisCatalog";
import type { AxisCatalogEntry } from "@/types/route";

export function catalogEntry(overrides: Partial<AxisCatalogEntry> & { axis_id: string }): AxisCatalogEntry {
  return {
    label: overrides.axis_id,
    description: "",
    category: "推定",
    default_weight: 0,
    display: { kind: "none", label: overrides.axis_id, category: "roadCondition", tile_inputs: [], thresholds: [] },
    icon_id: null,
    chip_label: null,
    panel_hint: null,
    show_map_icon: true,
    primary_attribute_ids: [],
    shape: {
      kind: "breakpoint_linear",
      terms: [{ material: "num_a", weight: 1, required: true }],
      preprocess: "identity",
      breakpoints: [
        [0, 0],
        [10, 100],
      ],
    },
    display_thresholds_override: null,
    display_band_labels_override: null,
    dedicated_way_value_layer: false,
    map_value_kind: "difficulty",
    map_value_unit: "",
    map_value_thresholds: null,
    raw_value_unit: null,
    raw_value_total_unit: null,
    material_breakdown: [],
    dynamic_way_value_needs_time: false,
    dynamic_way_value_needs_bearing: false,
    dynamic_way_value_needs_speed: false,
    ...overrides,
  };
}

/** タイルへ焼いた材料で塗るramp軸。 */
export function rampEntry(axisId: string, thresholds: number[], overrides: Partial<AxisCatalogEntry> = {}) {
  return catalogEntry({
    axis_id: axisId,
    display: {
      kind: "ramp",
      label: axisId,
      category: "roadCondition",
      tile_inputs: [
        {
          property: "num_a",
          weight: 1,
          boolean: false,
          true_value: 0,
          false_value: 0,
          has_unknown_fallback: false,
          needs_runtime_scale: false,
        },
      ],
      thresholds,
    },
    ...overrides,
  });
}

/** 配信された値で塗る専用配信軸。 */
export function dedicatedEntry(axisId: string, thresholds: number[], overrides: Partial<AxisCatalogEntry> = {}) {
  return catalogEntry({
    axis_id: axisId,
    dedicated_way_value_layer: true,
    map_value_thresholds: thresholds,
    ...overrides,
  });
}

export function catalogOf(entries: readonly AxisCatalogEntry[]): AxisCatalog {
  return axisCatalogFromResponse(entries, {}, {}, []);
}
