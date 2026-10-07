// 軸カタログ（`GET /api/axis-catalog`）の軸を、テストが自分で組むための雛形。型はbackendの契約から生成したもの。
//
// **実際の公開軸を入力に使わない。** 軸idは軸スタジオでユーザーが決める任意の値で、公開される集合もDBが持つ。
// **既定値は型を満たすための空だけ**（段の境界だけは、backendが宣言の無い軸にも必ず入れる既定の境界）。見たい性質
// （ramp表示を持つ・専用配信を持つ等）は呼び出し側が書く。
import { axisCatalogFromResponse, type AxisCatalog } from "@/lib/axisCatalog";
import { mapDisplay } from "@/types/generated/mapDisplay";
import type { AxisCatalogEntry, AxisCatalogResponse } from "@/types/route";

type MapPaint = AxisCatalogEntry["map_paint"];
type TileInput = MapPaint["tiles"]["tile_inputs"][number];

/** 軸1本の上書き。地図が塗るもの（`map_paint`）とその中のタイルの塗り（`tiles`）、生値の単位（`raw_value_units`）は
 * 一部だけを上書きできる。 */
type EntryOverrides = Partial<Omit<AxisCatalogEntry, "map_paint" | "raw_value_units">> & {
  map_paint?: Partial<Omit<MapPaint, "tiles">> & { tiles?: Partial<MapPaint["tiles"]> };
  raw_value_units?: Partial<AxisCatalogEntry["raw_value_units"]>;
};

/** 数値の材料をそのまま足すタイルの入力。 */
export function tileInput(overrides: Partial<TileInput> = {}): TileInput {
  return {
    property: "",
    weight: 0,
    boolean: false,
    true_value: 0,
    false_value: 0,
    has_unknown_fallback: false,
    categories: null,
    breakpoints: null,
    needs_runtime_scale: false,
    ...overrides,
  };
}

/** 軸1本。 */
export function catalogEntry(overrides: EntryOverrides = {}): AxisCatalogEntry {
  const { map_paint: { tiles, ...mapPaint } = {}, raw_value_units: rawValueUnits, ...rest } = overrides;
  const axisId = rest.axis_id ?? "";
  // 境界を宣言していない軸にbackendが入れる既定の境界（空の境界は塗りの式にならない）。
  const thresholds = mapPaint.thresholds ?? [...mapDisplay.valueScale.difficultyBoundaries];
  return {
    axis_id: axisId,
    label: axisId,
    description: "",
    category: "推定",
    default_weight: 0,
    icon_id: null,
    primary_attribute_ids: [],
    weather_layer_groups: [],
    dedicated_way_value_layer: false,
    map_paint: {
      value: { kind: "difficulty" },
      unit: "",
      thresholds,
      // 凡例は塗る値の境界を得点として書く（量で書く軸は呼び出し側が上書きする）。
      legend: { boundaries: thresholds, unit: null },
      band_labels: null,
      ...mapPaint,
      tiles: { kind: "none", tile_inputs: [], thresholds: [], ...tiles },
    },
    raw_value_units: { unit: null, total_unit: null, ...rawValueUnits },
    material_breakdown: [],
    dynamic_way_value_conditions: [],
    dynamic_way_value_undetermined_by_bearing: false,
    ...rest,
  };
}

/** タイルへ焼いた材料で塗るramp軸。 */
export function rampEntry(axisId: string, thresholds: number[], overrides: EntryOverrides = {}) {
  return catalogEntry({
    axis_id: axisId,
    ...overrides,
    map_paint: {
      legend: { boundaries: thresholds, unit: null },
      ...overrides.map_paint,
      tiles: { kind: "ramp", tile_inputs: [tileInput()], thresholds, ...overrides.map_paint?.tiles },
    },
  });
}

/** 配信された値で塗る専用配信軸。 */
export function dedicatedEntry(axisId: string, thresholds: number[], overrides: EntryOverrides = {}) {
  return catalogEntry({
    axis_id: axisId,
    dedicated_way_value_layer: true,
    ...overrides,
    map_paint: { thresholds, ...overrides.map_paint },
  });
}

/** 軸だけを持つ応答。軸以外（較正値・タイルの世代・事故の収録年）は、見たい呼び出し側が上書きする。 */
export function catalogResponse(
  entries: readonly AxisCatalogEntry[],
  overrides: Partial<Omit<AxisCatalogResponse, "axes">> = {},
): AxisCatalogResponse {
  return {
    axes: [...entries],
    tile_runtime_scales: {},
    client_tuning: {},
    tile_versions: {},
    accident_years: [],
    ...overrides,
  };
}

/** 本番と同じ`axisCatalogFromResponse`を通したカタログ。 */
export function catalogOf(entries: readonly AxisCatalogEntry[]): AxisCatalog {
  return axisCatalogFromResponse(catalogResponse(entries));
}
