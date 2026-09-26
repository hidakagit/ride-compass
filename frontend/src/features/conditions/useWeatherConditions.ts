"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { getQueryClient } from "@/lib/queryClient";
import {
  getAmedasObservation,
  getCurrentWeather,
  getFloodForecasts,
  getWbgtStatus,
  getWeatherWarnings,
} from "@/services/weatherApi";
import refreshIntervals from "@/types/generated/refresh-intervals.json";
import type { Coordinates } from "@/types/route";
import type { AmedasObservation, WeatherConditions } from "@/types/weather";
import type { WarningBadgeItem, WarningFetchFailure } from "@/features/conditions/WarningBadge/WarningBadge";

interface UseWeatherConditionsResult {
  /** 今日の見通し（予報）。常設のヘッダーは読まない（ヘッダーは実測、見通しは予報）。 */
  weather: WeatherConditions | null;
  weatherLoading: boolean;
  weatherError: string | null;
  /** 最寄りのアメダスの実測（常設のヘッダー）。予報の成否・遅さに引きずられないよう別に取る。 */
  amedas: AmedasObservation | null;
  amedasLoading: boolean;
  amedasError: string | null;
  /** 警報・注意報・暑さ指数・河川氾濫予報のバッジ。 */
  warningBadgeItems: WarningBadgeItem[];
  /** 警告の取得に失敗した出所。 */
  warningFetchFailures: WarningFetchFailure[];
}

interface LocationFetchState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

// 一定の間隔で取り直す（間隔はアメダスの更新に合わせる。警報は随時更新。一度きりだと、一時の失敗も残り続ける）。
const WEATHER_REFRESH_INTERVAL_MS = refreshIntervals.amedas_seconds * 1000;

/** 位置が決まるまで待ち、位置が変わるたびに取り直す。位置を変えて取り直している間と、取り直しに失敗した後は前の値を
 * 残し、失敗には`error`を添える（消したい呼ぶ側は`error`を見て自分で落とす）。`key`は取得の種類の名前（同じ位置の
 * 同じ種類は画面をまたいで1つの取得を共有する）。 */
function useLocationFetch<T>(
  key: string,
  fetcher: (location: Coordinates) => Promise<T>,
  location: Coordinates,
  locationReady: boolean,
): LocationFetchState<T> {
  const { data, error, isFetching } = useQuery(
    {
      queryKey: ["location-weather", key, location.latitude, location.longitude],
      queryFn: () => fetcher(location),
      enabled: locationReady,
      placeholderData: keepPreviousData,
      refetchInterval: WEATHER_REFRESH_INTERVAL_MS,
    },
    getQueryClient(),
  );
  return { data: data ?? null, loading: isFetching, error: error?.message ?? null };
}

export function useWeatherConditions(location: Coordinates, locationReady: boolean): UseWeatherConditionsResult {
  const weather = useLocationFetch("forecast", getCurrentWeather, location, locationReady);
  const amedas = useLocationFetch("amedas", getAmedasObservation, location, locationReady);

  // 警告は、取れない間その出所のバッジを出さず、失敗した出所を別に渡す（バッジが無いのを「警告なし」と読ませない）。
  // backendの中の失敗は空の応答で届くので、ここで拾えるのは通信の失敗・429等だけ。
  const warnings = useLocationFetch("warnings", getWeatherWarnings, location, locationReady);
  const wbgt = useLocationFetch("wbgt", getWbgtStatus, location, locationReady);
  const flood = useLocationFetch("flood", getFloodForecasts, location, locationReady);
  const weatherWarnings = warnings.error ? null : warnings.data;
  const wbgtStatus = wbgt.error ? null : wbgt.data;
  const floodForecasts = flood.error ? null : flood.data;

  const warningBadgeItems = useMemo<WarningBadgeItem[]>(() => {
    const jmaItems: WarningBadgeItem[] = weatherWarnings
      ? weatherWarnings.warnings.map((warning) => ({
          id: warning.code,
          label: warning.name,
          level: warning.level,
          source: "jma",
          title: [
            warning.additions.length > 0 ? `付随事項: ${warning.additions.join("・")}` : null,
            "取得できない場合は警報が出ていてもバッジが表示されないことがあります",
          ]
            .filter(Boolean)
            .join(" / "),
        }))
      : [];
    // 暑さ指数は段が無い間（提供期間外・「ほぼ安全」等）は出さない。
    const wbgtItem: WarningBadgeItem[] =
      wbgtStatus?.level && wbgtStatus.value != null
        ? [
            {
              id: "wbgt",
              label: `暑さ指数${wbgtStatus.label ?? ""}`,
              level: wbgtStatus.level,
              source: "wbgt",
              title: `暑さ指数 ${wbgtStatus.value.toFixed(1)} / 取得できない場合は警戒レベルに関わらずバッジが表示されないことがあります`,
            },
          ]
        : [];
    const floodItems: WarningBadgeItem[] = (floodForecasts?.forecasts ?? []).map((forecast) => ({
      id: `flood-${forecast.river_code}`,
      label: forecast.label,
      level: forecast.badge_level,
      source: "flood",
      title: `${forecast.condition} / 取得できない場合は氾濫予報が出ていてもバッジが表示されないことがあります`,
    }));
    return [...jmaItems, ...wbgtItem, ...floodItems];
  }, [weatherWarnings, wbgtStatus, floodForecasts]);

  const warningFetchFailures = useMemo<WarningFetchFailure[]>(
    () =>
      [
        { id: "jma", label: "警報・注意報", error: warnings.error },
        { id: "wbgt", label: "暑さ指数", error: wbgt.error },
        { id: "flood", label: "河川氾濫予報", error: flood.error },
      ].flatMap(({ id, label, error }) => (error ? [{ id, label, detail: error }] : [])),
    [warnings.error, wbgt.error, flood.error],
  );

  return {
    weather: weather.data,
    weatherLoading: weather.loading,
    weatherError: weather.error,
    amedas: amedas.data,
    amedasLoading: amedas.loading,
    amedasError: amedas.error,
    warningBadgeItems,
    warningFetchFailures,
  };
}
