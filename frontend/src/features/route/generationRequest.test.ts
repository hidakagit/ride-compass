// @vitest-environment node
/**
 * `features/route/generationRequest.ts`——生成の入力から、backendへ送る値と「生成条件が変わったか」の比較キーを作る。
 * - `buildGenerateRequest`: 決まった項目は常に送り、目標距離・重み・経由地・目的地は値があるときだけ送る
 * - `generationConditionsKey`: 送る値のうち、利用者が選んでいない出発時刻を除いたものが同じなら同じキー。
 *   重み・除外の項目の並びは比べない
 *
 * ここで見ないもの:
 * - 画面の状態から入力を組み立てること・キーの違いを印にすること → `useRouteGeneration.test.ts`
 * - 乗り換えの評価に生成の入力を使い回すこと → `useSpliceSession.test.ts`
 */
import { describe, expect, it } from "vitest";

import { buildGenerateRequest, generationConditionsKey, type GenerationInput } from "./generationRequest";

const START = new Date("2026-10-04T01:30:00Z");

const LOOP: GenerationInput = {
  origin: { latitude: 35.68, longitude: 139.77 },
  distanceKm: 40,
  distanceToleranceKm: 5,
  maxRoutes: 3,
  assumedSpeedKmh: 22,
  startTime: START,
  hardFilters: { exclude_a: true, exclude_b: false },
  routePreference: null,
  waypoints: [],
  destination: null,
  startTimePinned: false,
};

describe("buildGenerateRequest", () => {
  it("地点を置かなければ、出発地・目標距離・幅・除外・候補数・速度・出発時刻を送り、値の無い項目は載せない", () => {
    expect(buildGenerateRequest(LOOP)).toEqual({
      latitude: 35.68,
      longitude: 139.77,
      distance_km: 40,
      distance_tolerance_km: 5,
      hard_filters: { exclude_a: true, exclude_b: false },
      max_routes: 3,
      assumed_speed_kmh: 22,
      start_time: "2026-10-04T01:30:00.000Z",
    });
  });

  it("目標距離が無ければ距離を載せず、置いた経由地と目的地を送る", () => {
    const waypoints = [
      { latitude: 35.7, longitude: 139.8 },
      { latitude: 35.71, longitude: 139.81 },
    ];
    const request = buildGenerateRequest({
      ...LOOP,
      distanceKm: null,
      waypoints,
      destination: { latitude: 35.75, longitude: 139.85 },
    });
    expect(request).not.toHaveProperty("distance_km");
    expect(request.waypoints).toEqual(waypoints);
    expect(request.destination).toEqual({ latitude: 35.75, longitude: 139.85 });
  });

  it("重みを上書きしていれば重みを送る", () => {
    const request = buildGenerateRequest({ ...LOOP, routePreference: { wind: 0.4, slope: 0.6 } });
    expect(request.route_preference).toEqual({ wind: 0.4, slope: 0.6 });
  });
});

describe("generationConditionsKey", () => {
  const key = (overrides: Partial<GenerationInput>) => generationConditionsKey({ ...LOOP, ...overrides });

  it("送る値（除外）が変われば、キーが変わる", () => {
    expect(key({ hardFilters: { exclude_a: false, exclude_b: false } })).not.toBe(key({}));
  });

  it("出発時刻は、利用者が選んだときだけ比べる", () => {
    const later = new Date(START.getTime() + 5 * 60 * 1000);
    expect(key({ startTime: later })).toBe(key({}));
    expect(key({ startTime: later, startTimePinned: true })).not.toBe(key({ startTimePinned: true }));
  });

  it("除外・重みの項目の並びが違うだけなら、キーは変わらない", () => {
    expect(
      key({ hardFilters: { exclude_b: false, exclude_a: true }, routePreference: { slope: 0.6, wind: 0.4 } }),
    ).toBe(key({ routePreference: { wind: 0.4, slope: 0.6 } }));
  });

  it("経由地の順番が違えば、キーが変わる", () => {
    const a = { latitude: 35.7, longitude: 139.8 };
    const b = { latitude: 35.71, longitude: 139.81 };
    expect(key({ waypoints: [a, b] })).not.toBe(key({ waypoints: [b, a] }));
  });
});
