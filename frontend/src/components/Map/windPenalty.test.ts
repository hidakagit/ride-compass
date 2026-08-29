// @vitest-environment node
import { describe, expect, it } from "vitest";
import { windPenalty, windPenaltyGridToCellFeatureCollection } from "./windPenalty";
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
