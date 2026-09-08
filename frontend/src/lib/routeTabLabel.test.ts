// @vitest-environment node
import { describe, expect, it } from "vitest";
import { extraDistanceLabel, shortestDistanceKm } from "./routeTabLabel";

const SHORTEST = { distance_km: 18.0, is_shortest_distance: true };
const LONGER = { distance_km: 22.0, is_shortest_distance: false };

describe("shortestDistanceKm", () => {
  it("基準線となる候補の距離を返す", () => {
    expect(shortestDistanceKm([LONGER, SHORTEST])).toBe(18.0);
  });

  it("基準線が無ければnull（周回モードや最短経路を求められなかった場合）", () => {
    expect(shortestDistanceKm([LONGER, { distance_km: 25.0 }])).toBeNull();
  });
});

describe("extraDistanceLabel", () => {
  it("最短より何km余分に走るかを出す", () => {
    expect(extraDistanceLabel(LONGER, 18.0)).toBe("+4.0");
  });

  it("基準線そのものには出さない", () => {
    expect(extraDistanceLabel(SHORTEST, 18.0)).toBeNull();
  });

  it("基準線が無ければ出さない", () => {
    expect(extraDistanceLabel(LONGER, null)).toBeNull();
  });

  it("差が丸めて0.0kmになるなら出さない（0を並べても判断材料にならない）", () => {
    expect(extraDistanceLabel({ distance_km: 18.02 }, 18.0)).toBeNull();
  });

  it("最短と同じ経路でなくても距離が同じなら出さない", () => {
    expect(extraDistanceLabel({ distance_km: 18.0 }, 18.0)).toBeNull();
  });
});
