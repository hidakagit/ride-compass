// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FloodForecasts, WbgtStatus, WeatherConditions, WeatherWarnings, WindGridPoint } from "@/types/weather";
import {
  getCurrentWeather,
  getFloodForecasts,
  getWbgtStatus,
  getWeatherWarnings,
  getWindGrid,
  getWindGridDetail,
} from "./weatherApi";

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
      weather_code: 1,
      is_day: 1,
      sunset: "2026-08-14T18:30",
      precipitation_probability_max_percent: 40,
      wind_speed_max_ms: 6.0,
      temperature_max_c: 30.0,
      temperature_min_c: 24.0,
      uv_index_max: 8.0,
      today_periods: [],
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

describe("getWbgtStatus", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時は/api/weather/wbgtをlatitude/longitude付きでfetchし、JSONをそのまま返す", async () => {
    const status: WbgtStatus = {
      level: "severe_warning",
      label: "厳重警戒",
      value: 30.0,
      observed_at: "2026/08/22 18:00:00",
    };
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => status }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getWbgtStatus({ latitude: 35.6812, longitude: 139.7671 });

    expect(result).toEqual(status);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/weather/wbgt");
    expect(String(url)).toContain("latitude=35.6812");
    expect(String(url)).toContain("longitude=139.7671");
  });

  it("ok:falseの場合はdetailとx-request-idからエラーメッセージを組み立てて投げる", async () => {
    const headers = new Headers({ "x-request-id": "req-654" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse({ ok: false, status: 429, json: async () => ({ detail: "リクエストが多すぎます" }), headers }),
      ),
    );

    await expect(getWbgtStatus({ latitude: 35.0, longitude: 139.0 })).rejects.toThrow(
      "リクエストが多すぎます[req: req-654]",
    );
  });
});

describe("getFloodForecasts", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時は/api/weather/flood-forecastをlatitude/longitude付きでfetchし、JSONをそのまま返す", async () => {
    const forecasts: FloodForecasts = {
      forecasts: [
        {
          river_code: "830304004400",
          river_name: "神田川",
          level: 4,
          badge_level: "severe_warning",
          label: "神田川氾濫危険警報",
          condition: "レベル４氾濫危険警報（発表）",
          report_datetime: "2026-08-22T17:50:00+09:00",
        },
      ],
    };
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => forecasts }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getFloodForecasts({ latitude: 35.6812, longitude: 139.7671 });

    expect(result).toEqual(forecasts);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/weather/flood-forecast");
    expect(String(url)).toContain("latitude=35.6812");
    expect(String(url)).toContain("longitude=139.7671");
  });

  it("ok:falseの場合はdetailとx-request-idからエラーメッセージを組み立てて投げる", async () => {
    const headers = new Headers({ "x-request-id": "req-852" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse({ ok: false, status: 429, json: async () => ({ detail: "リクエストが多すぎます" }), headers }),
      ),
    );

    await expect(getFloodForecasts({ latitude: 35.0, longitude: 139.0 })).rejects.toThrow(
      "リクエストが多すぎます[req: req-852]",
    );
  });
});

describe("getWindGrid", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // 改善計画T203: バックエンドはtimes配列をpoints各点からは外し、応答トップレベルに
  // 1本だけ持つ形（WindGridResponse）で返す。フロント内部の表現（WindGridPoint、各点が
  // timesを持つ）は変えないため、weatherApi.ts側でtimesを各点へ合成し直して返す。
  it("成功時は/api/weather/wind-gridをfetchし、times配列を各点へ合成して返す", async () => {
    const response = {
      times: ["2026-08-20T12:00"],
      points: [
        {
          latitude: 35.68,
          longitude: 139.77,
          wind_speed_ms: [2.5],
          wind_direction_deg: [90],
          precipitation_mm: [0.5],
        },
      ],
    };
    const expected: WindGridPoint[] = [{ ...response.points[0], times: response.times }];
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => response }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getWindGrid();

    expect(result).toEqual(expected);
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

  it("成功時は/api/weather/wind-grid-detailをbboxクエリ付きでfetchし、times配列を各点へ合成して返す", async () => {
    const response = {
      times: ["2026-08-20T12:00"],
      points: [
        {
          latitude: 35.68,
          longitude: 139.77,
          wind_speed_ms: [2.5],
          wind_direction_deg: [90],
          precipitation_mm: [0.5],
        },
      ],
    };
    const expected: WindGridPoint[] = [{ ...response.points[0], times: response.times }];
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => response }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getWindGridDetail(bbox, 0.01);

    expect(result).toEqual(expected);
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
