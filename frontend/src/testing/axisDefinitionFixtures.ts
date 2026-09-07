import type { AxisDefinitionResponse } from "@/types/route";

/**
 * 軸スタジオのテストが土台に使う軸定義。勾配軸（タイル非依存・未公開）を素にして、
 * 各テストが必要なフィールドだけoverridesで差し替える。
 *
 * `display`はAxisDefinitionResponseの必須フィールド（backendのaxis_display_for()の
 * 計算結果）。gradient_percentはタイルを引かないためkind="none"が実際の値と一致する。
 */
export function baseAxisDefinition(
  overrides: Partial<AxisDefinitionResponse> = {},
): AxisDefinitionResponse {
  return {
    axis_id: "gradient",
    label: "勾配",
    description: "",
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
      terms: [{ material: "gradient_percent", weight: 1.0, required: true }],
      preprocess: "identity",
      breakpoints: [
        [0, 0],
        [10, 100],
      ],
    },
    display: { kind: "none", label: "勾配", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
    ...overrides,
  };
}
