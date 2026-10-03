// @vitest-environment node
/**
 * 編集で作ったルートの元との違い（`editDifference`）——指標の差と、変えた区間の元の位置・長さの差。
 */
import { describe, expect, it } from "vitest";

import { makeRouteCandidate } from "@/testing/routeFixtures";

import { editDifference, formatDelta } from "./routeEditDiff";

// 赤道の上を東へ0.01度（約1.11km）ずつ進む元と、2本目のEdgeだけを北へ膨らむ道へ替えたルート。
const ORIGIN = makeRouteCandidate({
  id: "origin",
  distance_km: 5.56,
  estimated_duration_seconds: 1200,
  overall_difficulty: { average: 40, load: 222 },
  edge_ids: ["e1", "a1", "e2", "a2", "e3"],
  edge_point_offsets: [0, 1, 2, 3, 4, 5],
  geometry: {
    type: "LineString",
    coordinates: [
      [0, 0],
      [0.01, 0],
      [0.02, 0],
      [0.03, 0],
      [0.04, 0],
      [0.05, 0],
    ],
  },
});
const EDITED = makeRouteCandidate({
  id: "edited",
  distance_km: 6.02,
  estimated_duration_seconds: 1080,
  overall_difficulty: { average: 35, load: 211 },
  edge_ids: ["e1", "b1", "e2", "a2", "e3"],
  edge_point_offsets: [0, 1, 3, 4, 5, 6],
  geometry: {
    type: "LineString",
    coordinates: [
      [0, 0],
      [0.01, 0],
      [0.015, 0.005],
      [0.02, 0],
      [0.03, 0],
      [0.04, 0],
      [0.05, 0],
    ],
  },
});

describe("editDifference", () => {
  it("指標は編集後 − 元で、変えた区間は元の始点からの位置と、変えた後の長さとの差", () => {
    const difference = editDifference(ORIGIN, EDITED);
    expect(difference.distanceKm).toBeCloseTo(0.46, 5);
    expect(difference).toMatchObject({ durationSeconds: -120, difficulty: -5, load: -11, stretchCount: 1 });
    expect(difference.stretches).toHaveLength(1);
    const [stretch] = difference.stretches;
    expect(stretch.startKm).toBeCloseTo(1.112, 3);
    expect(stretch.endKm).toBeCloseTo(2.224, 3);
    expect(stretch.lengthDiffKm).toBeCloseTo(0.461, 3);
  });

  it("どちらかが値を持たない指標は差をnullにする", () => {
    const difference = editDifference(
      { ...ORIGIN, estimated_duration_seconds: null },
      { ...EDITED, overall_difficulty: null },
    );
    expect(difference).toMatchObject({ durationSeconds: null, difficulty: null, load: null });
  });

  it("Edgeの境界を持たない候補では、変えた区間を数えるが位置は出さない", () => {
    const difference = editDifference({ ...ORIGIN, edge_point_offsets: [] }, EDITED);
    expect(difference.stretchCount).toBe(1);
    expect(difference.stretches).toEqual([]);
  });
});

describe("formatDelta", () => {
  it("表示する桁で丸め、符号を付ける。丸めて0なら「±0」", () => {
    expect(formatDelta(0.46, 1)).toBe("+0.5");
    expect(formatDelta(-2.4, 0)).toBe("−2");
    expect(formatDelta(0.04, 1)).toBe("±0");
  });
});
