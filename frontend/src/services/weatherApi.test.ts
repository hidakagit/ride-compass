// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WeatherConditions } from "@/types/weather";
import { getCurrentWeather } from "./weatherApi";

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
      "天候の取得に失敗しました[HTTP 503]",
    );
  });
});
