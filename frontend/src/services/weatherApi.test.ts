// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WeatherConditions, WeatherWarnings, WindGridPoint } from "@/types/weather";
import { getCurrentWeather, getWeatherWarnings, getWindGrid, getWindGridDetail } from "./weatherApi";

function makeResponse(overrides: Partial<{ ok: boolean; status: number; json: () => Promise<unknown>; headers: Headers }>) {
  return {
    ok: true,
    status: 200,
    json: async () => ({}),
    headers: new Headers(),
    ...overrides,
  };
}

describe("getCurrentWeather", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時はlatitude/longitudeをクエリに含むURLでfetchし、JSONをそのまま返す", async () => {
    const weather: WeatherConditions = {
      temperature_c: 20.5,
      apparent_temperature_c: 21.2,
      wind_speed_ms: 3.2,
      wind_direction_deg: 90,
      wind_direction_label: "東",
      wind_gusts_ms: 5.1,
      precipitation_probability_percent: 10,
      precipitation_mm: 0.1,
      uv_index: 3.5,
      observed_at: "2026-08-14T00:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => weather }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getCurrentWeather({ latitude: 35.1234, longitude: 139.5678 });

    expect(result).toEqual(weather);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("latitude=35.1234");
    expect(String(url)).toContain("longitude=139.5678");
  });

  it("ok:falseの場合はdetailとx-request-idからエラーメッセージを組み立てて投げる", async () => {
    const headers = new Headers({ "x-request-id": "req-456" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse({
          ok: false,
          status: 500,
          json: async () => ({ detail: "天候取得エラー" }),
          headers,
        }),
      ),
    );

    await expect(getCurrentWeather({ latitude: 35.0, longitude: 139.0 })).rejects.toThrow(
      "天候取得エラー[req: req-456]",
    );
  });

  it("errorBodyのjson parseが失敗した場合はフォールバックメッセージになる", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse({
          ok: false,
          status: 503,
          json: async () => {
            throw new Error("parse failed");
          },
          headers: new Headers(),
        }),
      ),
    );

    await expect(getCurrentWeather({ latitude: 35.0, longitude: 139.0 })).rejects.toThrow(
      "天候情報の取得に失敗しました[HTTP 503]",
    );
  });
});

describe("getWeatherWarnings", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時は/api/weather/warningsをlatitude/longitude付きでfetchし、JSONをそのまま返す", async () => {
    const warnings: WeatherWarnings = {
      area_name: "東京地方",
      report_datetime: "2026-08-22T18:09:00+09:00",
      warnings: [{ code: "14", name: "雷注意報", level: "advisory", additions: ["竜巻"] }],
    };
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => warnings }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getWeatherWarnings({ latitude: 35.6812, longitude: 139.7671 });

    expect(result).toEqual(warnings);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/weather/warnings");
    expect(String(url)).toContain("latitude=35.6812");
    expect(String(url)).toContain("longitude=139.7671");
  });

  it("ok:falseの場合はdetailとx-request-idからエラーメッセージを組み立てて投げる", async () => {
    const headers = new Headers({ "x-request-id": "req-321" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse({ ok: false, status: 429, json: async () => ({ detail: "リクエストが多すぎます" }), headers }),
      ),
    );

    await expect(getWeatherWarnings({ latitude: 35.0, longitude: 139.0 })).rejects.toThrow(
      "リクエストが多すぎます[req: req-321]",
    );
  });
});

describe("getWindGrid", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時は/api/weather/wind-gridをfetchし、格子点配列をそのまま返す", async () => {
    const grid: WindGridPoint[] = [
      {
        latitude: 35.68,
        longitude: 139.77,
        times: ["2026-08-20T12:00"],
        wind_speed_ms: [2.5],
        wind_direction_deg: [90],
        precipitation_mm: [0.5],
      },
    ];
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => grid }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getWindGrid();

    expect(result).toEqual(grid);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/weather/wind-grid");
  });

  it("ok:falseの場合はdetailとx-request-idからエラーメッセージを組み立てて投げる", async () => {
    const headers = new Headers({ "x-request-id": "req-789" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse({ ok: false, status: 429, json: async () => ({ detail: "リクエストが多すぎます" }), headers }),
      ),
    );

    await expect(getWindGrid()).rejects.toThrow("リクエストが多すぎます[req: req-789]");
  });
});

describe("getWindGridDetail", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const bbox = { minLon: 139.7, minLat: 35.6, maxLon: 139.8, maxLat: 35.7 };

  it("成功時は/api/weather/wind-grid-detailをbboxクエリ付きでfetchし、格子点配列をそのまま返す", async () => {
    const grid: WindGridPoint[] = [
      {
        latitude: 35.68,
        longitude: 139.77,
        times: ["2026-08-20T12:00"],
        wind_speed_ms: [2.5],
        wind_direction_deg: [90],
        precipitation_mm: [0.5],
      },
    ];
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => grid }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getWindGridDetail(bbox, 0.01);

    expect(result).toEqual(grid);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/weather/wind-grid-detail");
    expect(String(url)).toContain("min_lon=139.7");
    expect(String(url)).toContain("max_lat=35.7");
    expect(String(url)).toContain("spacing_deg=0.01");
  });

  it("ok:falseの場合はdetailとx-request-idからエラーメッセージを組み立てて投げる", async () => {
    const headers = new Headers({ "x-request-id": "req-999" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse({ ok: false, status: 400, json: async () => ({ detail: "表示範囲が広すぎます。ズームインしてください。" }), headers }),
      ),
    );

    await expect(getWindGridDetail(bbox, 0.02)).rejects.toThrow("表示範囲が広すぎます。ズームインしてください。[req: req-999]");
  });
});
