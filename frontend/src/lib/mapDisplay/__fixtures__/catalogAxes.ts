// 軸カタログ（`GET /api/axis-catalog`）の軸を、テストが自分で組むための雛形。型はbackendの契約から生成したもの。
//
// **実際の公開軸を入力に使わない。** 軸idは軸スタジオでユーザーが決める任意の値で、公開される集合もDBが持つ。
// **既定値は型を満たすための空だけ。** 見たい性質（ramp表示を持つ・専用配信を持つ等）は呼び出し側が書く。
import { axisCatalogFromResponse, type AxisCatalog } from "@/lib/axisCatalog";
import type { AxisCatalogEntry } from "@/types/route";

type TileInput = NonNullable<AxisCatalogEntry["display"]["tile_inputs"]>[number];

/** 数値の材料をそのまま足すタイルの入力。 */
export function tileInput(overrides: Partial<TileInput> = {}): TileInput {
  return {
    property: "",
    weight: 0,
    boolean: false,
    true_value: 0,
    false_value: 0,
    has_unknown_fallback: false,
    needs_runtime_scale: false,
    ...overrides,
  };
}

/** 軸1本。地図の表示の宣言（`display`）は一部だけを上書きできる。 */
export function catalogEntry(
  overrides: Partial<Omit<AxisCatalogEntry, "display">> & { display?: Partial<AxisCatalogEntry["display"]> } = {},
): AxisCatalogEntry {
  const { display, ...rest } = overrides;
  const axisId = rest.axis_id ?? "";
  return {
    axis_id: axisId,
    label: axisId,
    description: "",
    category: "推定",
    default_weight: 0,
    icon_id: null,
    chip_label: null,
    panel_hint: null,
    show_map_icon: false,
    primary_attribute_ids: [],
    shape: {
      kind: "breakpoint_linear",
      terms: [],
      preprocess: "identity",
      breakpoints: [],
    },
    display_thresholds_override: null,
    display_band_labels_override: null,
    dedicated_way_value_layer: false,
    map_value_kind: "difficulty",
    map_value_material: null,
    map_value_unit: "",
    map_value_thresholds: null,
    raw_value_unit: null,
    raw_value_total_unit: null,
    material_breakdown: [],
    dynamic_way_value_needs_time: false,
    dynamic_way_value_needs_bearing: false,
    dynamic_way_value_needs_speed: false,
    ...rest,
    display: { kind: "none", label: axisId, category: "roadCondition", tile_inputs: [], thresholds: [], ...display },
  };
}

/** タイルへ焼いた材料で塗るramp軸。 */
export function rampEntry(axisId: string, thresholds: number[], overrides: Partial<AxisCatalogEntry> = {}) {
  return catalogEntry({
    axis_id: axisId,
    display: { kind: "ramp", label: axisId, category: "roadCondition", tile_inputs: [tileInput()], thresholds },
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

/** 本番と同じ`axisCatalogFromResponse`を通したカタログ。 */
export function catalogOf(entries: readonly AxisCatalogEntry[]): AxisCatalog {
  return axisCatalogFromResponse(entries, {}, {}, []);
}
