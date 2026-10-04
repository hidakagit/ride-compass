// @vitest-environment node
/**
 * `features/route/routeEditDiff.ts`——編集で作ったルートが元から何を変えたか。
 * - `editDifference`: 距離・所要時間・総合難易度・負荷の差（編集後 − 元。どちらかに値が無ければnull）と、2本のEdgeの差から
 *   求めた変えた区間（元の始点からの位置と、長さの差）
 * - `formatDelta`: 差を表示の桁で丸めて符号付きで書く。丸めて0なら「±0」
 *
 * 経路はbackendの契約どおりの形を`testing/routeFixtures.ts: routeThrough`で地点の並びから組む。
 *
 * ここで見ないもの:
 * - 区間を対応づける規則（本数が食い違う・同じ道） → `routeSplice.test.ts`
 * - 差を並べて色を付けること → `EditDifference/EditDifference.test.tsx`・`RouteSplicePanel/RouteSplicePanel.test.tsx`
 */
import { describe, expect, it } from "vitest";

import { cumulativeDistancesKm } from "@/features/route/geoDistance";
import { makeRouteCandidate, routeThrough, type Places } from "@/testing/routeFixtures";
import type { RouteCandidate } from "@/types/route";

import { editDifference, formatDelta } from "./routeEditDiff";

// 東西に並ぶ元の道（A〜F）と、その北の地点（P〜R）。
const PLACES: Places = {
  A: [139.0, 35.0],
  B: [139.01, 35.0],
  C: [139.02, 35.0],
  D: [139.03, 35.0],
  E: [139.04, 35.0],
  F: [139.05, 35.0],
  P: [139.01, 35.01],
  Q: [139.02, 35.01],
  R: [139.04, 35.02],
};

function route(names: string, overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return makeRouteCandidate({ ...routeThrough(PLACES, [...names]), ...overrides });
}

/** 地点の並びをたどった長さ（km）。 */
function lengthKm(names: string): number {
  return cumulativeDistancesKm(routeThrough(PLACES, [...names]).geometry.coordinates).at(-1)!;
}

describe("editDifference", () => {
  it("距離・所要時間・総合難易度・負荷の差を、編集後から元を引いて出す", () => {
    const origin = route("ABCDEF", {
      distance_km: 20,
      estimated_duration_seconds: 3600,
      overall_difficulty: { average: 40, load: 800 },
    });
    const edited = route("ABQDEF", {
      distance_km: 21.5,
      estimated_duration_seconds: 3300,
      overall_difficulty: { average: 35, load: 752.5 },
    });
    expect(editDifference(origin, edited)).toMatchObject({
      distanceKm: 1.5,
      durationSeconds: -300,
      difficulty: -5,
      load: -47.5,
    });
  });

  it("どちらかに所要時間・総合難易度が無ければ、その差はnull", () => {
    const withValues = route("ABCDEF", {
      estimated_duration_seconds: 3600,
      overall_difficulty: { average: 40, load: 800 },
    });
    const withoutValues = route("ABQDEF", { estimated_duration_seconds: null, overall_difficulty: null });
    for (const [origin, edited] of [
      [withValues, withoutValues],
      [withoutValues, withValues],
    ]) {
      expect(editDifference(origin, edited)).toMatchObject({ durationSeconds: null, difficulty: null, load: null });
    }
  });

  it("変えた区間を、元の始点からの位置と、変えた後の長さ − 元の長さで、起点に近い順に出す", () => {
    const difference = editDifference(route("ABCDEF"), route("APCDRF"));
    const expected = [
      { startKm: 0, endKm: lengthKm("ABC"), lengthDiffKm: lengthKm("APC") - lengthKm("ABC") },
      { startKm: lengthKm("ABCD"), endKm: lengthKm("ABCDEF"), lengthDiffKm: lengthKm("DRF") - lengthKm("DEF") },
    ];
    difference.stretches.forEach((stretch, index) => {
      expect(stretch.startKm).toBeCloseTo(expected[index].startKm, 10);
      expect(stretch.endKm).toBeCloseTo(expected[index].endKm, 10);
      expect(stretch.lengthDiffKm).toBeCloseTo(expected[index].lengthDiffKm, 10);
    });
    expect(difference.stretches).toHaveLength(2);
  });

  it("続けて当てた乗り換えが隣り合えば、1つの区間として数える", () => {
    // B〜CをPへ、C〜DをQへ替えた結果は、B〜Dを1つ替えたものとして見える。
    const difference = editDifference(route("ABCDE"), route("ABPQDE"));
    expect(difference.stretches).toHaveLength(1);
    expect(difference.stretches[0].startKm).toBeCloseTo(lengthKm("AB"), 10);
    expect(difference.stretches[0].endKm).toBeCloseTo(lengthKm("ABCD"), 10);
  });

  it("同じ道なら、変えた区間は無い", () => {
    expect(editDifference(route("ABCDE"), route("ABCDE")).stretches).toEqual([]);
  });
});

describe("formatDelta", () => {
  it.each([
    [0.44, 1, "+0.4"],
    [-2.04, 0, "−2"],
    [2, 1, "+2.0"],
    [-0.36, 1, "−0.4"],
  ])("%sを小数%s桁で書くと「%s」（減りはマイナス記号）", (value, digits, text) => {
    expect(formatDelta(value, digits)).toBe(text);
  });

  it.each([0, 0.04, -0.04])("%sは小数1桁へ丸めると0なので「±0」", (value) => {
    expect(formatDelta(value, 1)).toBe("±0");
  });
});
