// @vitest-environment node
import { describe, expect, it } from "vitest";
import type { RouteCandidate } from "@/types/route";
import { computeRouteBounds, routesToFeatureCollection } from "./MapView";

function makeCandidate(overrides: Partial<RouteCandidate>): RouteCandidate {
  return {
    id: "candidate-0",
    direction_label: "0度",
    distance_km: 15,
    geometry: { type: "LineString", coordinates: [[139.7, 35.7]] },
    elevation_gain_m: 100,
    min_elevation_m: 0,
    max_elevation_m: 50,
    max_gradient_percent: 5,
    wind_score: 1,
    road_score: 80,
    total_score: 70,
    score_breakdown: null,
    segments: null,
    overall_difficulty: 40,
    axis_difficulties: {},
    ...overrides,
  };
}

describe("routesToFeatureCollection", () => {
  it("選択中の候補が配列の最後（最前面）に描画されるよう並び替える", () => {
    const a = makeCandidate({ id: "a" });
    const b = makeCandidate({ id: "b" });
    const c = makeCandidate({ id: "c" });

    const collection = routesToFeatureCollection([a, b, c], "b");

    expect(collection.features.map((f) => f.properties.selected)).toEqual([false, false, true]);
    // bが最後（最前面）に来ている
    expect(collection.type).toBe("FeatureCollection");
    const lastFeature = collection.features[collection.features.length - 1];
    expect(lastFeature.properties.selected).toBe(true);
  });

  it("選択中の候補が無い場合は全区間selected:falseのまま順序も変わらない", () => {
    const a = makeCandidate({ id: "a" });
    const b = makeCandidate({ id: "b" });

    const collection = routesToFeatureCollection([a, b], null);

    expect(collection.features.map((f) => f.properties.selected)).toEqual([false, false]);
  });

  it("各featureのgeometryは候補のgeometryをそのまま使う", () => {
    const geometry: GeoJSON.LineString = {
      type: "LineString",
      coordinates: [
        [139.7, 35.7],
        [139.71, 35.71],
      ],
    };
    const collection = routesToFeatureCollection([makeCandidate({ id: "a", geometry })], "a");

    expect(collection.features[0].geometry).toEqual(geometry);
  });

  it("候補が0件ならfeaturesも空配列", () => {
    const collection = routesToFeatureCollection([], null);

    expect(collection.features).toEqual([]);
  });
});

describe("computeRouteBounds", () => {
  it("全候補の形状点を包含するboundsを返す", () => {
    const routes = [
      makeCandidate({
        id: "a",
        geometry: {
          type: "LineString",
          coordinates: [
            [139.70, 35.70],
            [139.72, 35.72],
          ],
        },
      }),
      makeCandidate({
        id: "b",
        geometry: {
          type: "LineString",
          coordinates: [
            [139.68, 35.68],
            [139.75, 35.75],
          ],
        },
      }),
    ];

    const bounds = computeRouteBounds(routes);

    // 全候補中の最小/最大経緯度を包含している
    expect(bounds.getWest()).toBeCloseTo(139.68);
    expect(bounds.getEast()).toBeCloseTo(139.75);
    expect(bounds.getSouth()).toBeCloseTo(35.68);
    expect(bounds.getNorth()).toBeCloseTo(35.75);
  });

  it("候補が0件でも空のboundsを返す（例外を投げない）", () => {
    const bounds = computeRouteBounds([]);

    expect(bounds.isEmpty()).toBe(true);
  });
});
