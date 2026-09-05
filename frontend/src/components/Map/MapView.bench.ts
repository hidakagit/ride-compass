// MapViewがルート候補受信のたびに行うGeoJSON構築処理のベンチマーク。
// `npm run test -- bench` ではなく、vitestのbench専用コマンドで実行する:
//   npx vitest bench src/components/Map/MapView.bench.ts
// （`npm run test`＝`vitest run`はbench()を実行しないため、通常のテストスイートには
// 影響しない。CI等に組み込む場合は別途`vitest bench`を呼ぶステップを追加すること。）
//
// 対象: routesToFeatureCollection/segmentsToFeatureCollection/computeRouteBounds。
// いずれもMapViewが候補ルート・選択状態が変わるたびに（`useEffect`経由で）呼ぶ純粋関数。
// 8方位分の候補、かつ各候補のgeometryはOSMの形状点をそのまま連結するため、
// 長い周回ルートでは数百〜数千点になりうる
// （`road_graph_engine.py: _concat_edge_geometries`参照）。ここでは30km周回を想定した
// 点数でベンチマークする。

import { bench, describe } from "vitest";
import type { RouteCandidate, RouteSegmentDetail } from "@/types/route";
import { computeRouteBounds, routesToFeatureCollection, segmentsToFeatureCollection } from "./MapView";

function makeGeometry(pointCount: number): GeoJSON.LineString {
  const coordinates: [number, number][] = [];
  for (let i = 0; i < pointCount; i++) {
    coordinates.push([139.7 + i * 0.0001, 35.7 + i * 0.0001]);
  }
  return { type: "LineString", coordinates };
}

function makeSegments(count: number): RouteSegmentDetail[] {
  const segments: RouteSegmentDetail[] = [];
  for (let i = 0; i < count; i++) {
    segments.push({
      // 実レスポンス同様、区間の道なり形状（数点のLineString）を持たせて計測する
      geometry: {
        type: "LineString",
        coordinates: [
          [139.7 + i * 0.001, 35.7 + i * 0.001],
          [139.7 + (i + 0.5) * 0.001, 35.7 + (i + 0.4) * 0.001],
          [139.7 + (i + 1) * 0.001, 35.7 + (i + 1) * 0.001],
        ],
      },
      start_latitude: 35.7 + i * 0.001,
      start_longitude: 139.7 + i * 0.001,
      end_latitude: 35.7 + (i + 1) * 0.001,
      end_longitude: 139.7 + (i + 1) * 0.001,
      cumulative_distance_km: i * 0.1,
      distance_km: 0.1,
      estimated_arrival_time: "2026-01-01T09:00:00+09:00",
      gradient_percent: (i % 10) - 5,
      wind_penalty: (i % 7) - 3,
      road_surface_good: i % 2 === 0,
      axis_difficulties: {
        gradient: (i * 7) % 100,
        wind: (i * 13) % 100,
        surface_q: (i * 17) % 100,
        stop_density: (i * 19) % 100,
        car_stress: (i * 23) % 100,
        accident: (i * 37) % 100,
        night: (i * 41) % 100,
      },
      material_values: {},
      axis_contributions: {
        gradient: (i * 7) % 100,
        wind: (i * 13) % 100,
        surface_q: (i * 17) % 100,
        stop_density: (i * 19) % 100,
        car_stress: (i * 23) % 100,
        accident: (i * 37) % 100,
        night: (i * 41) % 100,
      },
      difficulty: (i * 11) % 100,
    });
  }
  return segments;
}

function makeCandidates(candidateCount: number, pointsPerCandidate: number): RouteCandidate[] {
  const candidates: RouteCandidate[] = [];
  for (let i = 0; i < candidateCount; i++) {
    candidates.push({
      id: `candidate-${i}`,
      direction_label: `${i * 45}度`,
      distance_km: 15 + i,
      geometry: makeGeometry(pointsPerCandidate),
      elevation_gain_m: 120,
      min_elevation_m: 3,
      max_elevation_m: 45,
      max_gradient_percent: 8.2,
      wind_score: 1.5,
      road_score: 82.3,
      segments: makeSegments(Math.round(pointsPerCandidate / 12)),
      overall_difficulty: 45.6,
      axis_difficulties: {},
      material_values: {},
      axis_contributions: {},
    });
  }
  return candidates;
}

// 8方位・30km周回ルート級（1候補あたり形状点1500点）を標準ケースとする。
const CANDIDATES_STANDARD = makeCandidates(8, 1500);
const CANDIDATES_LARGE = makeCandidates(8, 6000); // 広域bboxで形状点密度が上がった場合を想定

describe("MapView GeoJSON construction", () => {
  bench("routesToFeatureCollection (8 candidates x 1500 points)", () => {
    routesToFeatureCollection(CANDIDATES_STANDARD, "candidate-3");
  });

  bench("routesToFeatureCollection (8 candidates x 6000 points)", () => {
    routesToFeatureCollection(CANDIDATES_LARGE, "candidate-3");
  });

  bench("computeRouteBounds (8 candidates x 1500 points)", () => {
    computeRouteBounds(CANDIDATES_STANDARD);
  });

  bench("computeRouteBounds (8 candidates x 6000 points)", () => {
    computeRouteBounds(CANDIDATES_LARGE);
  });

  bench("segmentsToFeatureCollection (125 segments, selected candidate)", () => {
    segmentsToFeatureCollection(CANDIDATES_STANDARD[3].segments ?? []);
  });
});
