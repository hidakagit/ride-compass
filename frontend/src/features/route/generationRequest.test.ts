// @vitest-environment node
import { describe, expect, it } from "vitest";

import { buildGenerateRequest, generationConditionsKey, type GenerationInput } from "./generationRequest";

const LOOP: GenerationInput = {
  origin: { latitude: 35.6, longitude: 139.7 },
  distanceKm: 30,
  distanceToleranceKm: 3,
  maxRoutes: 5,
  assumedSpeedKmh: 20,
  startTime: new Date("2026-09-24T09:00:00+09:00"),
  hardFilters: { stairs: true },
  lensAxisId: null,
  routePreference: null,
  waypoints: [],
  destination: null,
  startTimePinned: true,
};

const DESTINATION: GenerationInput = {
  ...LOOP,
  distanceKm: null,
  waypoints: [
    { latitude: 35.61, longitude: 139.71 },
    { latitude: 35.62, longitude: 139.72 },
  ],
  destination: { latitude: 35.7, longitude: 139.8 },
};

describe("buildGenerateRequest", () => {
  it("画面の値を送る形へ移す。開始時刻はISO形式", () => {
    const request = buildGenerateRequest(LOOP);
    expect(request).toMatchObject({
      latitude: 35.6,
      longitude: 139.7,
      distance_km: 30,
      distance_tolerance_km: 3,
      max_routes: 5,
      assumed_speed_kmh: 20,
      hard_filters: { stairs: true },
      start_time: "2026-09-24T00:00:00.000Z",
    });
  });

  it("レンズの軸・重みの上書き・経由地・目的地・距離は、値があるときだけ送る", () => {
    const loop = buildGenerateRequest(LOOP);
    for (const key of ["lens_axis_id", "route_preference", "waypoints", "destination"]) {
      expect(loop).not.toHaveProperty(key);
    }
    expect(buildGenerateRequest(DESTINATION)).not.toHaveProperty("distance_km");
    const full = buildGenerateRequest({ ...DESTINATION, lensAxisId: "wind", routePreference: { wind: 1 } });
    expect(full).toMatchObject({
      lens_axis_id: "wind",
      route_preference: { wind: 1 },
      waypoints: DESTINATION.waypoints,
      destination: DESTINATION.destination,
    });
  });

  it("経由地は渡した配列そのものではなく写しを送る", () => {
    expect(buildGenerateRequest(DESTINATION).waypoints).not.toBe(DESTINATION.waypoints);
  });
});

describe("generationConditionsKey（「生成条件が変更されています」の比較キー）", () => {
  const key = generationConditionsKey;

  it("送る値が変われば変わる", () => {
    const base = key(DESTINATION);
    const changed: Partial<GenerationInput>[] = [
      { distanceKm: 31 },
      { distanceToleranceKm: 2 },
      { assumedSpeedKmh: 22 },
      { hardFilters: { stairs: false } },
      { routePreference: { wind: 1 } },
      { origin: { latitude: 35.5, longitude: 139.7 } },
      { destination: { latitude: 35.71, longitude: 139.8 } },
      { waypoints: [...DESTINATION.waypoints].reverse() },
      { maxRoutes: 6 },
      { startTime: new Date("2026-09-24T10:00:00+09:00") },
    ];
    for (const change of changed) expect(key({ ...DESTINATION, ...change })).not.toBe(base);
  });

  it("レンズの軸は比べない（地図の見え方の選択で、候補の選定に影響しない）", () => {
    expect(key({ ...LOOP, lensAxisId: "wind" })).toBe(key(LOOP));
  });

  it("出発時刻は、利用者が選んでいない間は比べない（「今」へ追従して勝手に進む）", () => {
    const following = { ...LOOP, startTimePinned: false };
    expect(key({ ...following, startTime: new Date("2026-09-24T09:05:00+09:00") })).toBe(key(following));
  });

  it("中身が同じなら、除外条件・重みのキーの並びが違っても同じ", () => {
    const a = { ...LOOP, hardFilters: { stairs: true, unpaved: false }, routePreference: { a: 0.3, b: 0.7 } };
    const b = { ...LOOP, hardFilters: { unpaved: false, stairs: true }, routePreference: { b: 0.7, a: 0.3 } };
    expect(key(a)).toBe(key(b));
  });
});
