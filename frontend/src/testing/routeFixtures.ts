import type { RouteCandidate } from "@/types/route";

/**
 * テスト・ベンチで使う`RouteCandidate`の組み立て。
 *
 * `RouteCandidate`は`Omit<Required<...>>`で全フィールドが必須のため、素直に書くと
 * 構築するファイルの数だけ全フィールドの写しができ、フィールドを1つ足すたびに同じ数の
 * 差分が要る。ここを唯一の置き場にして、呼び出し側は変えたいフィールドだけ渡す。
 */
export function makeRouteCandidate(overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return {
    id: "route-1",
    direction_label: "北",
    distance_km: 30,
    geometry: { type: "LineString", coordinates: [] },
    elevation_gain_m: null,
    min_elevation_m: null,
    max_elevation_m: null,
    segments: null,
    overall_difficulty: null,
    difficulty_load: null,
    axis_difficulties: {},
    material_values: {},
    material_category_shares: {},
    axis_raw_values: {},
    edge_ids: [],
    edge_point_offsets: [],
    is_shortest_distance: false,
    axis_contributions: {},
    ...overrides,
  };
}
