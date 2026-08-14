export interface Coordinates {
  latitude: number;
  longitude: number;
}

export type LocationSource = "geolocation" | "manual" | "default";

export interface RouteSegment {
  distance_km: number;
  duration_minutes: number;
  geometry: GeoJSON.LineString;
}

export interface RoutePreviewRequest {
  origin: Coordinates;
  destination: Coordinates;
}

export interface RouteSegmentDetail {
  start_latitude: number;
  start_longitude: number;
  end_latitude: number;
  end_longitude: number;
  cumulative_distance_km: number;
  distance_km: number;
  estimated_arrival_time: string | null;
  gradient_percent: number | null;
  wind_penalty: number | null;
  road_surface_good: boolean | null;
  elevation_difficulty: number | null;
  wind_difficulty: number | null;
  road_difficulty: number | null;
  difficulty: number | null;
}

export interface RouteCandidate {
  id: string;
  direction_label: string;
  distance_km: number;
  geometry: GeoJSON.LineString;
  elevation_gain_m: number | null;
  min_elevation_m: number | null;
  max_elevation_m: number | null;
  max_gradient_percent: number | null;
  wind_score: number | null;
  road_score: number | null;
  total_score: number | null;
  segments: RouteSegmentDetail[] | null;
}

export interface RouteGenerateRequest {
  latitude: number;
  longitude: number;
  distance_km: number;
  distance_tolerance_km: number;
  route_type: "loop";
}
