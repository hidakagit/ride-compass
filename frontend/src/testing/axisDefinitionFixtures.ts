import type { AxisDefinitionResponse } from "@/types/route";

/**
 * 軸スタジオのテストが土台に使う軸定義。**実在の軸・材料は使わない**——「この軸だから
 * こうなる」がテストに混ざると、軸の定義が変わったときに関係の無いテストが落ちる。
 * 必要な特徴は各テストがoverridesで足す。
 */
export function baseAxisDefinition(overrides: Partial<AxisDefinitionResponse> = {}): AxisDefinitionResponse {
  return {
    axis_id: "axis_a",
    label: "軸A",
    description: "",
    weight_share_when_published: null,
    category: "観測",
    default_weight: 0.2,
    is_published: false,
    priority_overrides: [],
    show_map_icon: true,
    time_scope: "always",
    dedicated_way_value_layer: false,
    dynamic_way_value_needs_time: false,
    dynamic_way_value_needs_bearing: false,
    dynamic_way_value_needs_speed: false,
    shape: {
      kind: "breakpoint_linear",
      terms: [{ material: "num_a", weight: 1.0, required: true }],
      preprocess: "identity",
      breakpoints: [
        [0, 0],
        [10, 100],
      ],
    },
    display: {
      kind: "none",
      label: "軸A",
      category: "trafficSafety",
      tile_inputs: [],
      thresholds: [],
    },
    ...overrides,
  };
}
