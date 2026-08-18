// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  GenerationConditions,
  RouteCandidate,
  RouteGenerateRequest,
  RoutePreviewRequest,
  RouteSegment,
} from "@/types/route";
import { generateRoutes, previewRoute } from "./routeApi";

function makeResponse(overrides: Partial<{ ok: boolean; status: number; json: () => Promise<unknown>; headers: Headers }>) {
  return {
    ok: true,
    status: 200,
    json: async () => ({}),
    headers: new Headers(),
    ...overrides,
  };
}

describe("routeApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe("previewRoute", () => {
    const request: RoutePreviewRequest = {
      origin: { latitude: 35.0, longitude: 139.0 },
      destination: { latitude: 35.1, longitude: 139.1 },
    };

    it("成功時はレスポンスのJSONをそのまま返し、URLとmethodを検証する", async () => {
      const segment: RouteSegment = {
        distance_km: 12.3,
        duration_minutes: 45,
        geometry: { type: "LineString", coordinates: [] },
      };
      const fetchMock = vi.fn().mockResolvedValue(
        makeResponse({
          json: async () => segment,
        }),
      );
      vi.stubGlobal("fetch", fetchMock);

      const result = await previewRoute(request);

      expect(result).toEqual(segment);
      const [url, options] = fetchMock.mock.calls[0];
      expect(String(url)).toContain("/api/routes/preview");
      expect(options.method).toBe("POST");
    });

    it("ok:falseの場合はdetailとx-request-idからエラーメッセージを組み立てて投げる", async () => {
      const headers = new Headers({ "x-request-id": "req-123" });
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          makeResponse({
            ok: false,
            status: 502,
            json: async () => ({ detail: "エラー詳細" }),
            headers,
          }),
        ),
      );

      await expect(previewRoute(request)).rejects.toThrow("エラー詳細[req: req-123]");
    });

    it("x-request-idヘッダが無い場合はメッセージに(req: ...)が付かない", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          makeResponse({
            ok: false,
            status: 502,
            json: async () => ({ detail: "エラー詳細" }),
            headers: new Headers(),
          }),
        ),
      );

      await expect(previewRoute(request)).rejects.toThrow("エラー詳細");
      try {
        await previewRoute(request);
        throw new Error("should have thrown");
      } catch (e) {
        expect((e as Error).message).toBe("エラー詳細");
      }
    });

    it("ok:falseでjson()がrejectする場合はフォールバックメッセージになる", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          makeResponse({
            ok: false,
            status: 502,
            json: async () => {
              throw new Error("parse failed");
            },
            headers: new Headers(),
          }),
        ),
      );

      await expect(previewRoute(request)).rejects.toThrow("リクエストに失敗しました[HTTP 502]");
    });
  });

  describe("generateRoutes", () => {
    const request: RouteGenerateRequest = {
      latitude: 35.0,
      longitude: 139.0,
      distance_km: 30,
      distance_tolerance_km: 5,
      route_type: "loop",
    };

    it("成功時はroutes・conditions・engineを返す", async () => {
      const routes: RouteCandidate[] = [
        {
          id: "route-1",
          direction_label: "北",
          distance_km: 30,
          geometry: { type: "LineString", coordinates: [] },
          elevation_gain_m: null,
          min_elevation_m: null,
          max_elevation_m: null,
          max_gradient_percent: null,
          wind_score: null,
          road_score: null,
          stop_density: null,
          traffic_stress_score: null,
          bicycle_infra_score: null,
          intersection_density: null,
          accident_density: null,
          safety_score: null,
          total_score: null,
          score_breakdown: null,
          segments: null,
          overall_difficulty: null,
        },
      ];
      const conditions: GenerationConditions = {
        latitude: 35.0,
        longitude: 139.0,
        distance_km: 30,
        distance_tolerance_km: 5,
        scoring_weights: { distance_weight: 0.3, elevation_weight: 0.15, wind_weight: 0.3, road_weight: 0.25 },
        route_preference: {
          elevation_weight: 0.15, road_weight: 0.19, wind_weight: 0.26, stop_weight: 0.15,
          traffic_weight: 0.1, infra_weight: 0.1, intersection_weight: 0.05, accident_weight: 0.08,
          safety_weight: 0.1,
        },
        traffic_stress_recipe: {
          lanes_low_threshold: 1, lanes_low_adjustment: -1,
        },
        safety_recipe: {
          lit_adjustment: -1, tunnel_adjustment: 1,
        },
        road_suitability_recipe: {
          base_by_highway: { residential: 2 },
          cycleway_track_adjustment: -2, cycleway_lane_adjustment: -1, cycleway_shared_adjustment: -1,
        },
        motor_vehicle_density_recipe: {
          maxspeed_low_threshold: 30, maxspeed_low_adjustment: -1,
          maxspeed_high_threshold: 60, maxspeed_high_adjustment: 1,
          lanes_high_threshold: 4, lanes_high_adjustment: 1,
          designation_adjustment: 1,
        },
        generated_at: "2026-08-15T12:00:00+09:00",
      };
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          makeResponse({
            json: async () => ({ routes, engine: "road_graph", conditions }),
          }),
        ),
      );

      const result = await generateRoutes(request);

      expect(result).toEqual({ routes, engine: "road_graph", conditions });
    });
  });
});
