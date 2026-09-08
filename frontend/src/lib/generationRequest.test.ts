// @vitest-environment node
import { describe, expect, it } from "vitest";
import { buildGenerateRequest, generationConditionsKey, type GenerationInput } from "./generationRequest";

const BASE: GenerationInput = {
  origin: { latitude: 35.68, longitude: 139.76 },
  distanceKm: 30,
  distanceToleranceKm: 5,
  maxRoutes: 8,
  assumedSpeedKmh: 20,
  startTime: new Date("2026-09-08T09:00:00+09:00"),
  penaltyStrength: 1.0,
  hardFilters: { motorway: true, no_bicycle: true, trunk: true },
  lensAxisId: null,
  routePreference: null,
  waypoints: [],
  destination: null,
  maxRoutesRelevant: true,
};

function keyOf(overrides: Partial<GenerationInput>): string {
  return generationConditionsKey({ ...BASE, ...overrides });
}

describe("buildGenerateRequest", () => {
  it("省略可能なフィールドは値があるときだけ載せる", () => {
    const request = buildGenerateRequest(BASE);

    expect(request.lens_axis_id).toBeUndefined();
    expect(request.route_preference).toBeUndefined();
    expect(request.waypoints).toBeUndefined();
    expect(request.destination).toBeUndefined();
    expect(request.start_time).toBe(BASE.startTime.toISOString());
  });

  it("目的地モードの経由地・目的地を載せる", () => {
    const destination = { latitude: 35.7, longitude: 139.8 };
    const request = buildGenerateRequest({ ...BASE, waypoints: [destination], destination });

    expect(request.waypoints).toEqual([destination]);
    expect(request.destination).toEqual(destination);
  });
});

describe("generationConditionsKey", () => {
  it("同じ入力からは同じキーになる", () => {
    expect(keyOf({})).toBe(keyOf({}));
  });

  // 統合レビュー第5回の指摘1-5。payloadへ送るのに比較していなかった2フィールド。
  it("出発時刻の変更を検知する（朝に生成→夕方へ変えたら差分になる）", () => {
    expect(keyOf({ startTime: new Date("2026-09-08T18:00:00+09:00") })).not.toBe(keyOf({}));
  });

  it("送るフィールドの変更は既定で差分になる（距離・速度・重み・0次除外・経由地）", () => {
    expect(keyOf({ distanceKm: 40 })).not.toBe(keyOf({}));
    expect(keyOf({ assumedSpeedKmh: 25 })).not.toBe(keyOf({}));
    expect(keyOf({ routePreference: { gradient: 0.5 } })).not.toBe(keyOf({}));
    expect(keyOf({ hardFilters: { motorway: false, no_bicycle: true, trunk: true } })).not.toBe(keyOf({}));
    expect(keyOf({ waypoints: [{ latitude: 35.7, longitude: 139.8 }] })).not.toBe(keyOf({}));
    expect(keyOf({ origin: { latitude: 35.0, longitude: 139.0 } })).not.toBe(keyOf({}));
  });

  it("レンズは比較対象から外す（地図の見え方の選択で、候補の選定には影響しない）", () => {
    expect(keyOf({ lensAxisId: "wind" })).toBe(keyOf({}));
    expect(keyOf({ lensAxisId: "gradient" })).toBe(keyOf({ lensAxisId: "wind" }));
  });

  it("経由地を伴う目的地ルートでは候補件数を比較しない（backendが値を無視するため）", () => {
    const withWaypoint = { waypoints: [{ latitude: 35.7, longitude: 139.8 }], maxRoutesRelevant: false };

    expect(keyOf({ ...withWaypoint, maxRoutes: 3 })).toBe(keyOf({ ...withWaypoint, maxRoutes: 8 }));
  });

  it("周回モードでは候補件数の変更を検知する", () => {
    expect(keyOf({ maxRoutes: 3 })).not.toBe(keyOf({}));
  });

  it("キーはフィールドの並び順に依存しない", () => {
    // オブジェクトのキー順が違うだけで差分と誤判定しないこと（比較前にソートしている）。
    const a = generationConditionsKey({ ...BASE, hardFilters: { motorway: true, no_bicycle: true, trunk: true } });
    const b = generationConditionsKey({ ...BASE, hardFilters: { trunk: true, motorway: true, no_bicycle: true } });

    expect(a).toBe(b);
  });
});
