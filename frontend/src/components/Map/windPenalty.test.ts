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
    expect(coarseGridPointsOutsideDetailBounds(coarse, [], 0.1, 0.02)).toEqual(coarse);
  });

  it("excludes a coarse point only when its entire cell is covered by the detail grid's extent", () => {
    const coarse = [
      makePoint(35.7, 139.7), // セル[35.65-35.75, 139.65-139.75]が、詳細格子の実カバー範囲
      // （点35.6/35.8・spacing0.02の半分ぶん外側へ拡張した[35.59-35.81, 139.59-139.81]）に
      // 余裕を持って収まる → 除外される。
      makePoint(35.9, 139.9), // 詳細格子のカバー範囲から大きく外れる → 残る
    ];
    const detail = [makePoint(35.6, 139.6), makePoint(35.8, 139.8)];
    const result = coarseGridPointsOutsideDetailBounds(coarse, detail, 0.1, 0.02);
    expect(result).toEqual([makePoint(35.9, 139.9)]);
  });

  it("does not exclude a coarse point whose cell extends beyond the detail grid's actual (small) coverage", () => {
    // 粗い格子1セル(coarseSpacingDeg=0.1、約11km四方)は、ズームインしたときの詳細格子の
    // 実際のカバー範囲（狭いbboxに絞られる、clampWindDetailBbox参照）よりずっと大きいことが
    // ある。この場合、粗い格子点の中心が詳細格子のすぐ近くにあっても、詳細格子は
    // セルの一部分（下記では[35.795-35.825, 139.795-139.825]という数百m四方）しか
    // 覆っていないため、セル全体は除外してはならない（除外すると、詳細格子が実際には
    // 覆っていない残りの部分が粗い格子でも詳細格子でも塗られない穴になる）。
    const coarse = [makePoint(35.8, 139.8)]; // セル[35.75-35.85, 139.75-139.85]
    const detail = [makePoint(35.8, 139.8), makePoint(35.82, 139.82)];
    const result = coarseGridPointsOutsideDetailBounds(coarse, detail, 0.1, 0.01);
    expect(result).toEqual(coarse);
  });
});
