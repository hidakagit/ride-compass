// @vitest-environment node
/**
 * `weatherApi.ts`——地点を渡す取得は緯度経度をクエリに付けて応答をそのまま返し、風の格子は応答の時刻の列を各点へ
 * 配り直すこと。失敗の扱いは共通の`fetchJson`が持つ（`lib/fetchJson.test.ts`）。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import * as weatherApi from "./weatherApi";
import { makeResponse } from "@/testing/fetchMocks";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => body }));
  vi.stubGlobal("fetch", fetchMock);
  return () => new URL(String(fetchMock.mock.calls[0][0]));
}

const POINT_GETTERS = [
  weatherApi.getCurrentWeather,
  weatherApi.getAmedasObservation,
  weatherApi.getWeatherWarnings,
  weatherApi.getWbgtStatus,
  weatherApi.getFloodForecasts,
];

describe("地点を渡す取得", () => {
  it.each(POINT_GETTERS.map((get) => [get.name, get] as const))(
    "%s は緯度経度をクエリに付けて取り、応答をそのまま返す",
    async (_name, get) => {
      const body = { precipitation_mm: 0, marker: "応答" };
      const url = stubFetch(body);
      await expect(get({ latitude: 35.1234, longitude: 139.5678 })).resolves.toEqual(body);
      expect(url().searchParams.get("latitude")).toBe("35.1234");
      expect(url().searchParams.get("longitude")).toBe("139.5678");
    },
  );
});

describe("風の格子", () => {
  const response = {
    times: ["2026-08-20T12:00", "2026-08-20T13:00"],
    points: [
      { latitude: 35.68, longitude: 139.77, wind_speed_ms: [2.5, 3], wind_direction_deg: [90, 95] },
      { latitude: 35.7, longitude: 139.8, wind_speed_ms: [1, 1.5], wind_direction_deg: [180, 170] },
    ],
  };
  const expected = response.points.map((point) => ({ ...point, times: response.times }));

  it("固定の格子も詳細の格子も、応答の時刻の列を各点へ配り直す", async () => {
    stubFetch(response);
    await expect(weatherApi.getWindGrid()).resolves.toEqual(expected);
    stubFetch(response);
    await expect(weatherApi.getWindGridDetail({ minLon: 0, minLat: 0, maxLon: 1, maxLat: 1 }, 0.01)).resolves.toEqual(
      expected,
    );
  });

  it("詳細の格子は表示範囲と間隔をクエリに付ける", async () => {
    const url = stubFetch(response);
    await weatherApi.getWindGridDetail({ minLon: 139.7, minLat: 35.6, maxLon: 139.8, maxLat: 35.7 }, 0.02);
    expect(Object.fromEntries(url().searchParams)).toEqual({
      min_lon: "139.7",
      min_lat: "35.6",
      max_lon: "139.8",
      max_lat: "35.7",
      spacing_deg: "0.02",
    });
  });
});
