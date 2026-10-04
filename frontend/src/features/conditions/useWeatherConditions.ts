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
import type { WarningBadgeItem } from "@/features/conditions/WarningBadge/WarningBadge";
import type { FetchFailure } from "@/types/fetchFailure";

interface UseWeatherConditionsResult {
  /** 「今日」のパネル（数値予報モデルの計算値）。常設のヘッダーは読まない（ヘッダーは実測）。 */
  weather: WeatherConditions | null;
  weatherLoading: boolean;
  weatherError: string | null;
  /** 最寄りのアメダスの実測（常設のヘッダー）。モデル側の成否・遅さに引きずられないよう別に取る。 */
  amedas: AmedasObservation | null;
  amedasLoading: boolean;
  amedasError: string | null;
  /** 警報・注意報・暑さ指数・河川氾濫予報のバッジ。 */
  warningBadgeItems: WarningBadgeItem[];
  /** 警告の取得に失敗した出所。 */
  warningFetchFailures: FetchFailure[];
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
  locationKnown: boolean,
): LocationFetchState<T> {
  const { data, error, isFetching } = useQuery(
    {
      queryKey: ["location-weather", key, location.latitude, location.longitude],
      queryFn: () => fetcher(location),
      enabled: locationKnown,
      placeholderData: keepPreviousData,
      refetchInterval: WEATHER_REFRESH_INTERVAL_MS,
    },
    getQueryClient(),
  );
  return { data: data ?? null, loading: isFetching, error: error?.message ?? null };
}

export function useWeatherConditions(location: Coordinates, locationKnown: boolean): UseWeatherConditionsResult {
  const weather = useLocationFetch("forecast", getCurrentWeather, location, locationKnown);
  const amedas = useLocationFetch("amedas", getAmedasObservation, location, locationKnown);

  // 警告は、取れない間その出所のバッジを出さず、失敗した出所を別に渡す（バッジが無いのを「警告なし」と読ませない）。
  // 空の応答は「出ていない」だけを表し、backendが配信元から取れなかったときも失敗（502）で届く。
  const warnings = useLocationFetch("warnings", getWeatherWarnings, location, locationKnown);
  const wbgt = useLocationFetch("wbgt", getWbgtStatus, location, locationKnown);
  const flood = useLocationFetch("flood", getFloodForecasts, location, locationKnown);
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
          title: warning.additions.length > 0 ? `付随事項: ${warning.additions.join("・")}` : undefined,
        }))
      : [];
    // 暑さ指数は段が無い間（値の無い提供期間外・「ほぼ安全」等）は出さない。
    const wbgtReading = wbgtStatus?.reading;
    const wbgtItem: WarningBadgeItem[] = wbgtReading
      ? [
          {
            id: "wbgt",
            label: `暑さ指数${wbgtReading.label}`,
            level: wbgtReading.level,
            source: "wbgt",
            title: `暑さ指数 ${wbgtReading.value.toFixed(1)}`,
          },
        ]
      : [];
    const floodItems: WarningBadgeItem[] = (floodForecasts?.forecasts ?? []).map((forecast) => ({
      id: `flood-${forecast.river_code}`,
      label: forecast.label,
      level: forecast.badge_level,
      source: "flood",
      title: forecast.condition,
    }));
    return [...jmaItems, ...wbgtItem, ...floodItems];
  }, [weatherWarnings, wbgtStatus, floodForecasts]);

  const warningFetchFailures = useMemo<FetchFailure[]>(
    () =>
      [
        { id: "jma", label: "警報・注意報", error: warnings.error },
        { id: "wbgt", label: "暑さ指数", error: wbgt.error },
        { id: "flood", label: "河川氾濫予報", error: flood.error },
      ].flatMap(({ id, label, error }) =>
        error ? [{ id, label, detail: error, effect: "出ていてもバッジは表示されません。" }] : [],
      ),
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
