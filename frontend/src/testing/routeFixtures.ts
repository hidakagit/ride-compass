import type { GenerationConditions, RouteCandidate, RouteSegmentDetail } from "@/types/route";

/**
 * テスト・ベンチで使う`RouteCandidate`の組み立て。
 *
 * `RouteCandidate`は全フィールドが必須（backendは既定値の項目も必ず返す）のため、素直に書くと
 * 構築するファイルの数だけ全フィールドの写しができ、フィールドを1つ足すたびに同じ数の
 * 差分が要る。ここを唯一の置き場にして、呼び出し側は変えたいフィールドだけ渡す。
 * **既定値は型を満たすための空だけ。** 見たい値（id・方位・距離等）は呼び出し側が書く。
 */
export function makeRouteCandidate(overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return {
    id: "",
    direction_label: "",
    distance_km: 0,
    geometry: { type: "LineString", coordinates: [] },
    elevation_gain_m: null,
    min_elevation_m: null,
    max_elevation_m: null,
    segments: [],
    overall_difficulty: null,
    estimated_duration_seconds: null,
    wind_unavailable: false,
    missing_travel_data_share: null,
    axis_difficulties: {},
    material_values: {},
    material_category_shares: {},
    axis_raw_values: {},
    edge_ids: [],
    edge_point_offsets: [],
    node_ids: [],
    axis_contributions: {},
    ...overrides,
  };
}

/** 地点の名前 → [経度, 緯度]。 */
export type Places = Readonly<Record<string, readonly [number, number]>>;

/**
 * 地点を順に通る経路の形（`edge_ids`・`edge_point_offsets`・`node_ids`・`geometry`）を、backendの契約
 * （`backend/app/domain/route.py: RouteCandidate`）どおりに組む。Edge idは両端の地点の名前を「-」でつないだもの、
 * Node idは地点の名前。Edgeごとに中間点を1つ挟むので、Edgeの境界の位置（`edge_point_offsets`）は座標の位置と食い違う。
 */
export function routeThrough(
  places: Places,
  names: readonly string[],
): Pick<RouteCandidate, "edge_ids" | "edge_point_offsets" | "node_ids" | "geometry"> {
  const coordinates: number[][] = [];
  names.forEach((name, index) => {
    const [lon, lat] = places[name];
    if (index > 0) {
      const [prevLon, prevLat] = places[names[index - 1]];
      coordinates.push([(prevLon + lon) / 2, (prevLat + lat) / 2]);
    }
    coordinates.push([lon, lat]);
  });
  return {
    edge_ids: names.slice(1).map((name, index) => `${names[index]}-${name}`),
    edge_point_offsets: names.map((_, index) => index * 2),
    node_ids: [...names],
    geometry: { type: "LineString", coordinates },
  };
}

/** `GenerationConditions`（生成に使われた条件）の組み立て。既定値は`makeRouteCandidate`と同じく型を満たすための空だけ。 */
export function makeGenerationConditions(overrides: Partial<GenerationConditions> = {}): GenerationConditions {
  return {
    latitude: 0,
    longitude: 0,
    distance_km: 0,
    distance_tolerance_km: 0,
    route_preference: {},
    penalty_strength: 0,
    max_average_grade_percent: null,
    hard_filters: {},
    max_routes: 0,
    start_time: "",
    assumed_speed_kmh: 0,
    waypoints: null,
    destination: null,
    corrected_destination: null,
    generated_at: "",
    ...overrides,
  };
}

/** `RouteSegmentDetail`（候補の区間1つ）の組み立て。既定値は型を満たすための空だけ。 */
export function makeRouteSegment(overrides: Partial<RouteSegmentDetail> = {}): RouteSegmentDetail {
  return {
    geometry: null,
    start_latitude: 0,
    start_longitude: 0,
    end_latitude: 0,
    end_longitude: 0,
    cumulative_distance_km: 0,
    distance_km: 0,
    estimated_arrival_time: null,
    axis_difficulties: {},
    axis_contributions: {},
    material_values: {},
    axis_raw_values: {},
    difficulty: null,
    wind: null,
    ...overrides,
  };
}
