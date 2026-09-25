"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  getAmedasObservation,
  getCurrentWeather,
  getFloodForecasts,
  getWbgtStatus,
  getWeatherWarnings,
} from "@/services/weatherApi";
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

// 一定の間隔で取り直す（アメダスは10分ごと、警報は随時更新。一度きりだと、一時の失敗も残り続ける）。
const WEATHER_REFRESH_INTERVAL_MS = 10 * 60 * 1000;

/** 位置が決まるまで待ち、位置が変わるたびに取り直し、最後に出した要求の結果だけを反映する。失敗しても前の値は残し、
 * `error`を添える（消したい呼ぶ側は`error`を見て自分で落とす）。`fetcher`はモジュールの関数を渡す（描くたびに新しい
 * 関数だと取り直しが止まらない）。 */
function useLocationFetch<T>(
  fetcher: (location: Coordinates) => Promise<T>,
  location: Coordinates,
  locationReady: boolean,
): LocationFetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latestRequestId = useRef(0);

  useEffect(() => {
    if (!locationReady) return;
    let disposed = false;
    const run = () => {
      const requestId = ++latestRequestId.current;
      setLoading(true);
      fetcher(location)
        .then((result) => {
          if (disposed || requestId !== latestRequestId.current) return;
          setData(result);
          // 取り直せたら前回の失敗表示は役目を終える。
          setError(null);
        })
        .catch((cause: unknown) => {
          if (disposed || requestId !== latestRequestId.current) return;
          setError(cause instanceof Error ? cause.message : "不明なエラーが発生しました");
        })
        .finally(() => {
          if (disposed || requestId !== latestRequestId.current) return;
          setLoading(false);
        });
    };
    // effectの中で同期にsetStateしない（react-hooks/set-state-in-effect）。
    Promise.resolve().then(() => {
      if (!disposed) run();
    });
    const timer = setInterval(run, WEATHER_REFRESH_INTERVAL_MS);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [locationReady, location, fetcher]);

  return { data, loading, error };
}

export function useWeatherConditions(location: Coordinates, locationReady: boolean): UseWeatherConditionsResult {
  const weather = useLocationFetch(getCurrentWeather, location, locationReady);
  const amedas = useLocationFetch(getAmedasObservation, location, locationReady);

  // 警告は、取れない間その出所のバッジを出さず、失敗した出所を別に渡す（バッジが無いのを「警告なし」と読ませない）。
  // backendの中の失敗は空の応答で届くので、ここで拾えるのは通信の失敗・429等だけ。
  const warnings = useLocationFetch(getWeatherWarnings, location, locationReady);
  const wbgt = useLocationFetch(getWbgtStatus, location, locationReady);
  const flood = useLocationFetch(getFloodForecasts, location, locationReady);
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
