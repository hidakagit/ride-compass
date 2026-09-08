import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Coordinates } from "@/types/route";
import type {
  AmedasObservation,
  FloodForecasts,
  WbgtStatus,
  WeatherConditions,
  WeatherWarnings,
} from "@/types/weather";

vi.mock("@/services/weatherApi", () => ({
  getCurrentWeather: vi.fn(),
  getAmedasObservation: vi.fn(),
  getWeatherWarnings: vi.fn(),
  getWbgtStatus: vi.fn(),
  getFloodForecasts: vi.fn(),
}));

import {
  getAmedasObservation,
  getCurrentWeather,
  getFloodForecasts,
  getWbgtStatus,
  getWeatherWarnings,
} from "@/services/weatherApi";
import { useWeatherConditions } from "./useWeatherConditions";

const TOKYO: Coordinates = { latitude: 35.68, longitude: 139.76 };
const OSAKA: Coordinates = { latitude: 34.69, longitude: 135.5 };

function weatherAt(temperature: number): WeatherConditions {
  return {
    temperature_c: temperature,
    wind_speed_ms: 1,
    wind_direction_deg: 0,
    wind_direction_label: "北",
    precipitation_mm: 0,
    observed_at: "2026-09-09T09:00:00+09:00",
    weather_code: 0,
    is_day: 1,
    sunset: null,
    sunrise: null,
    precipitation_max_mm: null,
    wind_speed_max_ms: null,
    temperature_max_c: null,
    temperature_min_c: null,
    today_periods: [],
  };
}

function amedasAt(stationName: string): AmedasObservation {
  return {
    station_id: "44132",
    station_name: stationName,
    latitude: 35.69,
    longitude: 139.75,
    observed_at: "2026-09-09T09:00:00+09:00",
    temperature_c: 25,
    apparent_temperature_c: null,
    wind_speed_ms: null,
    wind_direction_deg: null,
    wind_direction_label: null,
    precipitation_10min_mm: null,
    sunshine_10min_minutes: null,
    sunrise: null,
    sunset: null,
  };
}

const NO_WARNINGS: WeatherWarnings = { area_name: null, report_datetime: null, warnings: [] };
const NO_WBGT: WbgtStatus = { level: null, label: null, value: null, observed_at: null };
const NO_FLOOD: FloodForecasts = { forecasts: [] };

/** 解決タイミングを呼び出し側から操作できるPromiseを返す。「古い応答が新しい応答を
 * 上書きしないか」の検証には、2回目を先に解決させてから1回目を解決させる必要がある。 */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  // 呼び出し元が解決させるまで待つPromiseのため、rejectを先に握り潰しておかないと
  // vitestが「未処理のrejection」として扱う。
  promise.catch(() => {});
  return { promise, resolve, reject };
}

/** 保留中のPromiseチェーン（then/catch/finallyの各段）が反映され切るまで待つ。
 * 「古い応答を握り潰す」ガードは*状態を更新しない*ことで働くため、waitForのような
 * 「条件が満たされるまで待つ」書き方では反映前に通過してしまい検証にならない。 */
async function flushPendingUpdates() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

/** 5種すべてを「取得成功・警告なし」にする。個別の検証対象だけを各テストで上書きする。 */
function mockAllQuiet() {
  vi.mocked(getCurrentWeather).mockResolvedValue(weatherAt(20));
  vi.mocked(getAmedasObservation).mockResolvedValue(amedasAt("東京"));
  vi.mocked(getWeatherWarnings).mockResolvedValue(NO_WARNINGS);
  vi.mocked(getWbgtStatus).mockResolvedValue(NO_WBGT);
  vi.mocked(getFloodForecasts).mockResolvedValue(NO_FLOOD);
}

describe("useWeatherConditions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("locationReadyがfalseの間はどのAPIも呼ばない", () => {
    mockAllQuiet();

    const { result } = renderHook(() => useWeatherConditions(TOKYO, false));

    expect(getCurrentWeather).not.toHaveBeenCalled();
    expect(getAmedasObservation).not.toHaveBeenCalled();
    expect(getWeatherWarnings).not.toHaveBeenCalled();
    expect(getWbgtStatus).not.toHaveBeenCalled();
    expect(getFloodForecasts).not.toHaveBeenCalled();
    expect(result.current.weather).toBeNull();
    expect(result.current.warningBadgeItems).toEqual([]);
  });

  it("locationReadyになると5種すべてを現在地でフェッチする", async () => {
    mockAllQuiet();

    const { result } = renderHook(() => useWeatherConditions(TOKYO, true));

    await waitFor(() => expect(result.current.weather).toEqual(weatherAt(20)));
    expect(result.current.amedas).toEqual(amedasAt("東京"));
    for (const api of [getCurrentWeather, getAmedasObservation, getWeatherWarnings, getWbgtStatus, getFloodForecasts]) {
      expect(api).toHaveBeenCalledWith(TOKYO);
    }
  });

  it("locationが変わると同じ5種を新しい座標で再フェッチする", async () => {
    mockAllQuiet();

    const { result, rerender } = renderHook(({ location }) => useWeatherConditions(location, true), {
      initialProps: { location: TOKYO },
    });
    await waitFor(() => expect(result.current.weather).not.toBeNull());

    rerender({ location: OSAKA });

    await waitFor(() => expect(getCurrentWeather).toHaveBeenCalledWith(OSAKA));
    for (const api of [getAmedasObservation, getWeatherWarnings, getWbgtStatus, getFloodForecasts]) {
      expect(api).toHaveBeenCalledWith(OSAKA);
    }
  });

  describe("古い応答が新しい応答を上書きしない（リクエストID競合ガード）", () => {
    it("weather: 後発が先に解決した後に先発が解決しても、後発の値のまま", async () => {
      const first = deferred<WeatherConditions>();
      const second = deferred<WeatherConditions>();
      mockAllQuiet();
      vi.mocked(getCurrentWeather).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

      const { result, rerender } = renderHook(({ location }) => useWeatherConditions(location, true), {
        initialProps: { location: TOKYO },
      });
      await waitFor(() => expect(getCurrentWeather).toHaveBeenCalledTimes(1));
      rerender({ location: OSAKA });
      await waitFor(() => expect(getCurrentWeather).toHaveBeenCalledTimes(2));

      second.resolve(weatherAt(30));
      await waitFor(() => expect(result.current.weather).toEqual(weatherAt(30)));
      first.resolve(weatherAt(10));
      await flushPendingUpdates();

      expect(result.current.weather).toEqual(weatherAt(30));
      expect(result.current.weatherLoading).toBe(false);
    });

    it("weather: 先発の失敗が後発の成功をエラーで塗り潰さない", async () => {
      const first = deferred<WeatherConditions>();
      const second = deferred<WeatherConditions>();
      mockAllQuiet();
      vi.mocked(getCurrentWeather).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

      const { result, rerender } = renderHook(({ location }) => useWeatherConditions(location, true), {
        initialProps: { location: TOKYO },
      });
      await waitFor(() => expect(getCurrentWeather).toHaveBeenCalledTimes(1));
      rerender({ location: OSAKA });
      await waitFor(() => expect(getCurrentWeather).toHaveBeenCalledTimes(2));

      second.resolve(weatherAt(30));
      await waitFor(() => expect(result.current.weather).toEqual(weatherAt(30)));
      first.reject(new Error("古い応答の失敗"));
      await flushPendingUpdates();

      expect(result.current.weatherError).toBeNull();
      expect(result.current.weather).toEqual(weatherAt(30));
      expect(result.current.weatherLoading).toBe(false);
    });

    it("amedas: 後発が先に解決した後に先発が解決しても、後発の値のまま", async () => {
      const first = deferred<AmedasObservation>();
      const second = deferred<AmedasObservation>();
      mockAllQuiet();
      vi.mocked(getAmedasObservation).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

      const { result, rerender } = renderHook(({ location }) => useWeatherConditions(location, true), {
        initialProps: { location: TOKYO },
      });
      await waitFor(() => expect(getAmedasObservation).toHaveBeenCalledTimes(1));
      rerender({ location: OSAKA });
      await waitFor(() => expect(getAmedasObservation).toHaveBeenCalledTimes(2));

      second.resolve(amedasAt("大阪"));
      await waitFor(() => expect(result.current.amedas?.station_name).toBe("大阪"));
      first.resolve(amedasAt("東京"));
      await flushPendingUpdates();

      expect(result.current.amedas?.station_name).toBe("大阪");
      expect(result.current.amedasLoading).toBe(false);
    });

    it("警告バッジ3種: 先発の失敗が後発の結果を消さない", async () => {
      const warningsFirst = deferred<WeatherWarnings>();
      const warningsSecond = deferred<WeatherWarnings>();
      const wbgtFirst = deferred<WbgtStatus>();
      const wbgtSecond = deferred<WbgtStatus>();
      const floodFirst = deferred<FloodForecasts>();
      const floodSecond = deferred<FloodForecasts>();
      mockAllQuiet();
      vi.mocked(getWeatherWarnings)
        .mockReturnValueOnce(warningsFirst.promise)
        .mockReturnValueOnce(warningsSecond.promise);
      vi.mocked(getWbgtStatus).mockReturnValueOnce(wbgtFirst.promise).mockReturnValueOnce(wbgtSecond.promise);
      vi.mocked(getFloodForecasts).mockReturnValueOnce(floodFirst.promise).mockReturnValueOnce(floodSecond.promise);

      const { result, rerender } = renderHook(({ location }) => useWeatherConditions(location, true), {
        initialProps: { location: TOKYO },
      });
      await waitFor(() => expect(getWeatherWarnings).toHaveBeenCalledTimes(1));
      rerender({ location: OSAKA });
      await waitFor(() => expect(getWeatherWarnings).toHaveBeenCalledTimes(2));

      warningsSecond.resolve({
        area_name: "大阪府",
        report_datetime: null,
        warnings: [{ code: "03", name: "大雨警報", level: "warning", additions: ["浸水害"] }],
      });
      wbgtSecond.resolve({ level: "advisory", label: "警戒", value: 28.4, observed_at: null });
      floodSecond.resolve({
        forecasts: [
          {
            river_code: "8606050001",
            river_name: "淀川",
            level: 3,
            badge_level: "warning",
            label: "淀川 氾濫警戒",
            condition: "氾濫警戒情報",
            report_datetime: "2026-09-09T09:00:00+09:00",
          },
        ],
      });
      await waitFor(() => expect(result.current.warningBadgeItems).toHaveLength(3));

      // 先発（東京ぶん）が後から失敗しても、表示中の大阪ぶんは消えない。
      warningsFirst.reject(new Error("古い応答の失敗"));
      wbgtFirst.reject(new Error("古い応答の失敗"));
      floodFirst.reject(new Error("古い応答の失敗"));
      await flushPendingUpdates();

      expect(result.current.warningBadgeItems).toHaveLength(3);
      expect(result.current.warningBadgeItems.map((item) => item.source)).toEqual(["jma", "wbgt", "flood"]);
    });
  });

  it("警告バッジ3種はいずれも取得失敗を例外にせず「警告なし」として扱う", async () => {
    mockAllQuiet();
    vi.mocked(getWeatherWarnings).mockRejectedValue(new Error("network error"));
    vi.mocked(getWbgtStatus).mockRejectedValue(new Error("network error"));
    vi.mocked(getFloodForecasts).mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useWeatherConditions(TOKYO, true));

    await waitFor(() => expect(result.current.weather).not.toBeNull());
    expect(result.current.warningBadgeItems).toEqual([]);
    expect(result.current.weatherError).toBeNull();
  });

  it("weather・amedasの失敗はそれぞれ独立してエラーになる", async () => {
    mockAllQuiet();
    vi.mocked(getCurrentWeather).mockRejectedValue(new Error("予報の取得に失敗"));

    const { result } = renderHook(() => useWeatherConditions(TOKYO, true));

    await waitFor(() => expect(result.current.weatherError).toBe("予報の取得に失敗"));
    expect(result.current.weather).toBeNull();
    // 実測（アメダス）は予報の失敗から独立して表示できる。
    expect(result.current.amedas).toEqual(amedasAt("東京"));
    expect(result.current.amedasError).toBeNull();
  });

  it("WBGTはlevelがあってもvalueがnullならバッジを出さない", async () => {
    mockAllQuiet();
    vi.mocked(getWbgtStatus).mockResolvedValue({
      level: "warning",
      label: "厳重警戒",
      value: null,
      observed_at: null,
    });

    const { result } = renderHook(() => useWeatherConditions(TOKYO, true));

    await waitFor(() => expect(result.current.weather).not.toBeNull());
    expect(result.current.warningBadgeItems).toEqual([]);
  });
});
