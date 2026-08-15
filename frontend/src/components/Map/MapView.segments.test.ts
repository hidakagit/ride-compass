import { describe, expect, it } from "vitest";
import type { RouteSegmentDetail } from "@/types/route";
import { segmentsToFeatureCollection } from "./MapView";

function makeSegment(overrides: Partial<RouteSegmentDetail>): RouteSegmentDetail {
  return {
    geometry: null,
    start_latitude: 35.7,
    start_longitude: 139.7,
    end_latitude: 35.71,
    end_longitude: 139.71,
    cumulative_distance_km: 0,
    distance_km: 1.0,
    estimated_arrival_time: null,
    gradient_percent: 1.2,
    wind_penalty: 0.5,
    road_surface_good: true,
    elevation_difficulty: 10,
    wind_difficulty: 20,
    road_difficulty: 0,
    difficulty: 12,
    ...overrides,
  };
}

describe("segmentsToFeatureCollection", () => {
  it("区間の道なり形状（geometry）があればそれをfeatureの形状に使う", () => {
    const geometry: GeoJSON.LineString = {
      type: "LineString",
      coordinates: [
        [139.7, 35.7],
        [139.703, 35.702], // 中間点＝カーブを表す形状点
        [139.71, 35.71],
      ],
    };
    const collection = segmentsToFeatureCollection([makeSegment({ geometry })]);

    expect(collection.features[0].geometry).toEqual(geometry);
  });

  it("geometryが無い区間は従来どおり始点・終点を結ぶ直線で代替する", () => {
    const collection = segmentsToFeatureCollection([makeSegment({ geometry: null })]);

    expect(collection.features[0].geometry).toEqual({
      type: "LineString",
      coordinates: [
        [139.7, 35.7],
        [139.71, 35.71],
      ],
    });
  });

  it("propertiesには形状を重複して持たせない（ポップアップ用の値だけを残す）", () => {
    const geometry: GeoJSON.LineString = {
      type: "LineString",
      coordinates: [
        [139.7, 35.7],
        [139.71, 35.71],
      ],
    };
    const collection = segmentsToFeatureCollection([makeSegment({ geometry })]);

    const properties = collection.features[0].properties;
    expect(properties).not.toHaveProperty("geometry");
    // 色分け式・ポップアップが参照する値は残っている
    expect(properties.wind_difficulty).toBe(20);
    expect(properties.gradient_percent).toBe(1.2);
    expect(properties.road_surface_good).toBe(true);
    expect(properties.difficulty).toBe(12);
  });
});
