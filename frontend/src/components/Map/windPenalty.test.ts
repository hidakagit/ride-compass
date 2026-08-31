// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  subtractRectangle,
  windPenalty,
  windPenaltyCoarseGridToClippedFeatureCollection,
  windPenaltyGridToCellFeatureCollection,
  type Rectangle,
} from "./windPenalty";
import type { WindGridPoint } from "@/types/weather";

describe("windPenalty", () => {
  it("matches the backend formula for a known headwind case", () => {
    // backend/app/domain/wind.py: WindCalculator.wind_penaltyのdocstring例と同じ考え方。
    // 風向（気象学=吹いてくる方向）=走行方位のとき、正面から風を受ける向かい風＝cos(0)=1で最大。
    expect(windPenalty(5, 90, 90)).toBeCloseTo(5, 6);
  });

  it("returns negative value for a tailwind", () => {
    // 風向と走行方位が180度ずれる＝追い風＝cos(180)=-1。
    expect(windPenalty(5, 90, 270)).toBeCloseTo(-5, 6);
  });

  it("returns near zero for a crosswind", () => {
    expect(windPenalty(5, 90, 0)).toBeCloseTo(0, 6);
  });
});

describe("windPenaltyGridToCellFeatureCollection", () => {
  const grid: WindGridPoint[] = [
    {
      latitude: 35.7,
      longitude: 139.7,
      wind_speed_ms: [4, 6],
      wind_direction_deg: [90, 180],
      precipitation_mm: [0, 0],
      times: ["2026-08-30T08:00", "2026-08-30T09:00"],
    },
  ];

  it("computes windPenalty per grid point using the shared bearing", () => {
    const fc = windPenaltyGridToCellFeatureCollection(grid, 1, 180, 0.1);
    expect(fc.features).toHaveLength(1);
    expect(fc.features[0].properties.windPenalty).toBeCloseTo(6, 6);
  });

  it("skips points with missing values at the given frame index", () => {
    const fc = windPenaltyGridToCellFeatureCollection(grid, 5, 0, 0.1);
    expect(fc.features).toHaveLength(0);
  });
});

describe("subtractRectangle", () => {
  const cell: Rectangle = { minLon: 0, maxLon: 10, minLat: 0, maxLat: 10 };

  it("returns the cell unchanged when hole does not overlap it", () => {
    const hole: Rectangle = { minLon: 20, maxLon: 30, minLat: 0, maxLat: 10 };
    expect(subtractRectangle(cell, hole)).toEqual([cell]);
  });

  it("returns nothing when hole fully covers the cell", () => {
    const hole: Rectangle = { minLon: -5, maxLon: 15, minLat: -5, maxLat: 15 };
    expect(subtractRectangle(cell, hole)).toEqual([]);
  });

  it("returns a single strip when hole overlaps only one edge", () => {
    const hole: Rectangle = { minLon: 6, maxLon: 20, minLat: -5, maxLat: 15 };
    expect(subtractRectangle(cell, hole)).toEqual([{ minLon: 0, maxLon: 6, minLat: 0, maxLat: 10 }]);
  });

  it("splits into 4 strips when hole sits entirely inside the cell (a donut)", () => {
    const hole: Rectangle = { minLon: 3, maxLon: 7, minLat: 3, maxLat: 7 };
    expect(subtractRectangle(cell, hole)).toEqual([
      { minLon: 0, maxLon: 3, minLat: 0, maxLat: 10 },
      { minLon: 7, maxLon: 10, minLat: 0, maxLat: 10 },
      { minLon: 3, maxLon: 7, minLat: 7, maxLat: 10 },
      { minLon: 3, maxLon: 7, minLat: 0, maxLat: 3 },
    ]);
  });
});

describe("windPenaltyCoarseGridToClippedFeatureCollection", () => {
  function makePoint(latitude: number, longitude: number): WindGridPoint {
    return { latitude, longitude, wind_speed_ms: [4], wind_direction_deg: [90], precipitation_mm: [0], times: ["2026-08-30T08:00"] };
  }

  it("returns one full-cell feature per coarse point when the detail grid is empty", () => {
    const coarse = [makePoint(35.7, 139.7), makePoint(35.9, 139.9)];
    const fc = windPenaltyCoarseGridToClippedFeatureCollection(coarse, [], 0, 90, 0.1, 0.02);
    expect(fc.features).toHaveLength(2);
    const ring = fc.features[0].geometry.coordinates[0];
    const expectedRing = [
      [139.65, 35.65],
      [139.75, 35.65],
      [139.75, 35.75],
      [139.65, 35.75],
      [139.65, 35.65],
    ];
    ring.forEach(([lon, lat], i) => {
      expect(lon).toBeCloseTo(expectedRing[i][0], 6);
      expect(lat).toBeCloseTo(expectedRing[i][1], 6);
    });
    expect(fc.features[0].properties.windPenalty).toBeCloseTo(windPenalty(4, 90, 90), 6);
  });

  it("skips points with missing values at the given frame index", () => {
    const fc = windPenaltyCoarseGridToClippedFeatureCollection([makePoint(35.7, 139.7)], [], 5, 90, 0.1, 0.02);
    expect(fc.features).toHaveLength(0);
  });

  it("clips a coarse cell into 4 pieces when the detail grid's coverage sits entirely inside it (does not double-render the overlap)", () => {
    // ユーザー報告「粗い格子と詳細格子が重なると色が二重に濃くなり凡例と対応しなくなる」
    // への対応（改善計画T515）。coarse点のセル[139.65-139.75, 35.65-35.75]の内側に、
    // detail点1点ぶんのカバー範囲[139.71-139.73, 35.69-35.71]（spacing0.02）が
    // すっぽり収まる（4隅すべてに余白がある）ため、重なった部分を除いた4枚の帯へ分解される。
    const coarse = [makePoint(35.7, 139.7)];
    const detail = [makePoint(35.7, 139.72)];
    const fc = windPenaltyCoarseGridToClippedFeatureCollection(coarse, detail, 0, 90, 0.1, 0.02);
    expect(fc.features).toHaveLength(4);
    for (const feature of fc.features) {
      expect(feature.properties.windPenalty).toBeCloseTo(windPenalty(4, 90, 90), 6);
    }
  });

  it("does not clip a coarse cell that the detail grid's coverage does not overlap at all", () => {
    const coarse = [makePoint(35.7, 139.7)];
    const detail = [makePoint(37.0, 141.0)]; // 遠く離れておりカバー範囲が重ならない
    const fc = windPenaltyCoarseGridToClippedFeatureCollection(coarse, detail, 0, 90, 0.1, 0.02);
    expect(fc.features).toHaveLength(1);
  });
});
