// ルート候補とその周り（生成の条件・区間）の組み立て。呼び出し側は変えたいフィールドだけ渡す。
// **既定値は型を満たすための空だけ。** 見たい値（id・方位・距離等）は呼び出し側が書く。
import type { GenerationConditions, PlaceCandidate, RouteCandidate, RouteSegmentDetail } from "@/types/route";

/** `RouteCandidate`の組み立て（backendは既定値の項目も必ず返すため、型は全フィールドが必須）。 */
export function makeRouteCandidate(overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return {
    id: "",
    kind: "loop",
    direction_label: "",
    is_fastest: false,
    spliceable: false,
    distance_km: 0,
    geometry: { type: "LineString", coordinates: [] },
    elevation_gain_m: null,
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

/** `GenerationConditions`（生成に使われた条件）の組み立て。 */
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

/** `RouteSegmentDetail`（候補の区間1つ）の組み立て。 */
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
    difficulty: null,
    wind: null,
    ...overrides,
  };
}

/** 字・丁目で当たった住所（その範囲の代表の位置）。 */
export const AZA_CANDIDATE: PlaceCandidate = {
  kind: "address",
  level: "aza",
  name: "東京都千代田区丸の内二丁目",
  area: null,
  latitude: 35.679,
  longitude: 139.764,
};

/** 名前で当たった施設（辺りを持つ）。 */
export const FACILITY_CANDIDATE: PlaceCandidate = {
  kind: "facility",
  level: "point",
  name: "浅草寺",
  area: "台東区浅草二丁目",
  latitude: 35.7148,
  longitude: 139.7967,
};
