// @vitest-environment node
import { describe, expect, it } from "vitest";
import { coarseGridPointsOutsideDetailBounds, windPenalty, windPenaltyGridToCellFeatureCollection } from "./windPenalty";
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

describe("coarseGridPointsOutsideDetailBounds", () => {
  function makePoint(latitude: number, longitude: number): WindGridPoint {
    return { latitude, longitude, wind_speed_ms: [4], wind_direction_deg: [90], precipitation_mm: [0], times: ["2026-08-30T08:00"] };
  }

  it("returns all coarse points unfiltered when the detail grid is empty", () => {
    const coarse = [makePoint(35.7, 139.7), makePoint(35.9, 139.9)];
    expect(coarseGridPointsOutsideDetailBounds(coarse, [], 0.1)).toEqual(coarse);
  });

  it("excludes a coarse point only when a detail point exists within half a coarse cell", () => {
    const coarse = [
      makePoint(35.7, 139.7), // 詳細格子点(35.71, 139.71)が半径0.05以内 → 除外される
      makePoint(35.9, 139.9), // 最寄りの詳細格子点まで遠い → 残る
    ];
    const detail = [makePoint(35.71, 139.71)];
    const result = coarseGridPointsOutsideDetailBounds(coarse, detail, 0.1);
    expect(result).toEqual([makePoint(35.9, 139.9)]);
  });

  it("does not exclude a coarse point that falls inside the detail grid's bounding box but has no nearby detail point (a gap within the detail grid)", () => {
    // 実機報告: 詳細格子が自身の外接矩形の内側を隙間なく埋めているとは限らない
    // （格子点の取得に一部失敗した等）。外接矩形だけで判定すると、詳細格子が実際には
    // 届いていない場所まで粗い格子ごと除外してしまい、両方とも描画されない穴ができる。
    const coarse = [makePoint(35.8, 139.8)]; // detailの外接矩形[35.7-35.9, 139.7-139.9]の内側だが、
    // 最も近いdetail点(35.7,139.7)/(35.9,139.9)からは半径0.05よりずっと遠い。
    const detail = [makePoint(35.7, 139.7), makePoint(35.9, 139.9)];
    const result = coarseGridPointsOutsideDetailBounds(coarse, detail, 0.1);
    expect(result).toEqual(coarse);
  });
});
