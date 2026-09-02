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

  describe("generateRoutes（改善計画T265: バックグラウンドジョブ化）", () => {
    const request: RouteGenerateRequest = {
      latitude: 35.0,
      longitude: 139.0,
      distance_km: 30,
      distance_tolerance_km: 5,
      route_type: "loop",
      penalty_strength: 1.0,
    };

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
        segments: null,
        overall_difficulty: null,
        axis_difficulties: {},
        axis_contributions: {},
      },
    ];
    const conditions: GenerationConditions = {
      latitude: 35.0,
      longitude: 139.0,
      distance_km: 30,
      distance_tolerance_km: 5,
      route_preference: {
        gradient: 0.15, surface_q: 0.19, wind: 0.26, stop_density: 0.2,
        car_stress: 0.2, accident: 0.08,
        night: 0.0,
      },
      penalty_strength: 1.0,
      max_average_grade_percent: null,
      hard_filters: { no_bicycle: true, motorway: true, trunk: true },
      waypoints: null,
      destination: null,
      generated_at: "2026-08-15T12:00:00+09:00",
    };

    /** POST /api/routes/generateはjob_idを、GET .../generate/{job_id}は
     * pollResponsesを順に1回ずつ返すfetchモック（複数回目以降は最後の要素を返し続ける）。 */
    function stubFetchForJob(pollResponses: unknown[]) {
      let pollCount = 0;
      const fetchMock = vi.fn().mockImplementation((url: string, options?: { method?: string }) => {
        if (options?.method === "POST") {
          return Promise.resolve(makeResponse({ json: async () => ({ job_id: "job-1" }) }));
        }
        const body = pollResponses[Math.min(pollCount, pollResponses.length - 1)];
        pollCount += 1;
        return Promise.resolve(makeResponse({ json: async () => body }));
      });
      vi.stubGlobal("fetch", fetchMock);
      return fetchMock;
    }

    afterEach(() => {
      vi.useRealTimers();
    });

    it("投稿直後（sleep無し）のポーリングで完了していればroutes・conditions・engineを返す", async () => {
      // 改善計画T386（T265コードレビュー指摘6件目）: 初回はsleepを挟まず即座にポーリング
      // するため、タイマーを進めなくても解決する。
      stubFetchForJob([{ status: "done", result: { routes, engine: "road_graph", conditions } }]);

      const result = await generateRoutes(request);

      expect(result).toEqual({ routes, engine: "road_graph", conditions });
    });

    it("改善計画T441: routesが空でno_candidates_reasonがある場合、noCandidatesReasonとして返し" +
      "warnレベルでdebugLogに記録する（SSHでサーバーログを見ずに原因が分かるようにする対応）", async () => {
      stubFetchForJob([
        {
          status: "done",
          result: { routes: [], engine: "road_graph", conditions, no_candidates_reason: "8方位すべてで経路探索に失敗しました" },
        },
      ]);

      const result = await generateRoutes(request);

      expect(result.noCandidatesReason).toBe("8方位すべてで経路探索に失敗しました");
      expect(debugLog).toHaveBeenCalledWith(
        "api:route",
        "8方位すべてで経路探索に失敗しました",
        expect.anything(),
        "warn",
      );
    });

    it("queued→runningの間はonProgressへ経過時間つきで通知し、doneで結果を返す", async () => {
      vi.useFakeTimers();
      stubFetchForJob([
        { status: "queued" },
        { status: "running" },
        { status: "done", result: { routes, engine: "road_graph", conditions } },
      ]);
      const onProgress = vi.fn();

      const resultPromise = generateRoutes(request, onProgress);
      // 初回ポーリングはsleep無しのため、2回目以降の分だけ進めればよい。
      await vi.advanceTimersByTimeAsync(1500 * 2);
      await resultPromise;

      expect(onProgress).toHaveBeenNthCalledWith(1, { status: "queued", elapsedMs: expect.any(Number) });
      expect(onProgress).toHaveBeenNthCalledWith(2, { status: "running", elapsedMs: expect.any(Number) });
      expect(onProgress).toHaveBeenCalledTimes(2); // doneの回はonProgressを呼ばない
    });

    it("failedの場合はerrorメッセージでrejectする", async () => {
      stubFetchForJob([{ status: "failed", error: "冷パスでタイムアウトしました" }]);

      await expect(generateRoutes(request)).rejects.toThrow("冷パスでタイムアウトしました");
    });

    it("6分経過してもdone/failedにならない場合はタイムアウトとしてrejectする", async () => {
      vi.useFakeTimers();
      stubFetchForJob([{ status: "running" }]); // 常にrunningを返し続ける

      const resultPromise = generateRoutes(request);
      resultPromise.catch(() => {}); // 未処理rejection警告を避ける（下でassertする）
      await vi.advanceTimersByTimeAsync(400000); // MAX_POLL_DURATION_MS(360000ms)を超える

      await expect(resultPromise).rejects.toThrow("タイムアウト");
    });

    it("onProgressへ渡すelapsedMsはGET応答が返った直後の最新値になる", async () => {
      // 改善計画T386（T265コードレビュー指摘8件目）: 以前はsleep・GETの前（古い時点）で
      // 計算していたため、実際の経過時間よりPOLL_INTERVAL_MS分ほど少なく表示され続けていた。
      vi.useFakeTimers();
      let pollCount = 0;
      const fetchMock = vi.fn().mockImplementation((url: string, options?: { method?: string }) => {
        if (options?.method === "POST") {
          return Promise.resolve(makeResponse({ json: async () => ({ job_id: "job-1" }) }));
        }
        pollCount += 1;
        if (pollCount === 1) {
          return Promise.resolve(makeResponse({ json: async () => ({ status: "running" }) }));
        }
        return Promise.resolve(
          makeResponse({ json: async () => ({ status: "done", result: { routes, engine: "road_graph", conditions } }) }),
        );
      });
      vi.stubGlobal("fetch", fetchMock);
      const onProgress = vi.fn();

      const resultPromise = generateRoutes(request, onProgress);
      await vi.advanceTimersByTimeAsync(1500);
      await resultPromise;

      // 1回目のポーリング（sleep無し、GET直後）で観測されたelapsedMsは、
      // POLL_INTERVAL_MS(1500ms)分の待機より前の極小値のはず。
      expect(onProgress).toHaveBeenCalledTimes(1);
      expect(onProgress.mock.calls[0][0].elapsedMs).toBeLessThan(1500);
    });

    it("ポーリングが一時的に失敗しても、規定回数までは生成全体を失敗させずリトライする", async () => {
      // 改善計画T386（T265コードレビュー指摘2件目）: 1回の一時的な通信エラー・5xxで
      // generateRoutes全体を即座に失敗させない。
      vi.useFakeTimers();
      let pollCount = 0;
      const fetchMock = vi.fn().mockImplementation((url: string, options?: { method?: string }) => {
        if (options?.method === "POST") {
          return Promise.resolve(makeResponse({ json: async () => ({ job_id: "job-1" }) }));
        }
        pollCount += 1;
        if (pollCount <= 2) {
          return Promise.resolve(makeResponse({ ok: false, status: 503, json: async () => ({ detail: "一時的なエラー" }) }));
        }
        return Promise.resolve(
          makeResponse({ json: async () => ({ status: "done", result: { routes, engine: "road_graph", conditions } }) }),
        );
      });
      vi.stubGlobal("fetch", fetchMock);

      const resultPromise = generateRoutes(request);
      await vi.advanceTimersByTimeAsync(1500 * 3);
      const result = await resultPromise;

      expect(result).toEqual({ routes, engine: "road_graph", conditions });
    });

    it("ポーリングの失敗が規定回数連続した場合は失敗としてrejectする", async () => {
      vi.useFakeTimers();
      const fetchMock = vi.fn().mockImplementation((url: string, options?: { method?: string }) => {
        if (options?.method === "POST") {
          return Promise.resolve(makeResponse({ json: async () => ({ job_id: "job-1" }) }));
        }
        return Promise.resolve(makeResponse({ ok: false, status: 503, json: async () => ({ detail: "サーバーエラー" }) }));
      });
      vi.stubGlobal("fetch", fetchMock);

      const resultPromise = generateRoutes(request);
      resultPromise.catch(() => {}); // 未処理rejection警告を避ける（下でassertする）
      await vi.advanceTimersByTimeAsync(1500 * 10);

      await expect(resultPromise).rejects.toThrow("サーバーエラー");
    });
  });
});
