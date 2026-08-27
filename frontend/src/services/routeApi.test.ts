// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  GenerationConditions,
  RouteCandidate,
  RouteGenerateRequest,
  RoutePreviewRequest,
  RouteSegment,
} from "@/types/route";
import { debugLog } from "@/lib/debugLog";
import { generateRoutes, previewRoute } from "./routeApi";

vi.mock("@/lib/debugLog", () => ({ debugLog: vi.fn() }));

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

    // 2026-08-24回帰テスト: fetch()自体が失敗する場合（タイムアウト・通信エラー）は
    // response.okのチェック以前の例外のため、try/catchで捕まえていないとdebugLogに
    // 一切記録が残らない（実機で「20kmルート生成がfail to fetchで失敗するがログに
    // 何も出ない」という報告を受けて発覚、lib/fetchJson.tsのGET用実装と同じ穴）。
    it("AbortSignal.timeoutによるタイムアウトはTimeoutErrorとしてdebugLogに記録した上で再送出する", async () => {
      const timeoutError = new DOMException("The operation was aborted.", "TimeoutError");
      vi.stubGlobal("fetch", vi.fn().mockRejectedValue(timeoutError));

      await expect(previewRoute(request)).rejects.toThrow(timeoutError.message);
      expect(debugLog).toHaveBeenCalledWith(
        "api:route",
        expect.stringContaining("タイムアウト"),
        expect.objectContaining({ error: expect.stringContaining("TimeoutError") }),
        "error",
      );
    });

    it("fetch()自体が失敗する通信エラー（バックエンド到達不能等）もdebugLogに記録した上で再送出する", async () => {
      const networkError = new TypeError("Failed to fetch");
      vi.stubGlobal("fetch", vi.fn().mockRejectedValue(networkError));

      await expect(previewRoute(request)).rejects.toThrow("Failed to fetch");
      expect(debugLog).toHaveBeenCalledWith(
        "api:route",
        "失敗 (通信エラー)",
        expect.objectContaining({ error: expect.stringContaining("Failed to fetch") }),
        "error",
      );
    });
  });

  describe("generateRoutes", () => {
    const request: RouteGenerateRequest = {
      latitude: 35.0,
      longitude: 139.0,
      distance_km: 30,
      distance_tolerance_km: 5,
      route_type: "loop",
      penalty_strength: 1.0,
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
          car_stress_score: null,
          bicycle_infra_score: null,
          intersection_density: null,
          accident_density: null,
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
          gradient: 0.15, surface_q: 0.19, wind: 0.26, stop_density: 0.2,
          car_stress: 0.2, accident: 0.08,
          night: 0.0,
        },
        penalty_strength: 1.0,
        max_average_grade_percent: null,
        hard_filters: { no_bicycle: true, motorway: true, trunk: true },
        waypoints: null,
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
