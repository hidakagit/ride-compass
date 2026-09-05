"use client";

// 現在地の天候（WeatherPanel向け）と3種の警告バッジ（JMA警報・注意報／WBGT／
// 河川氾濫予報）のフェッチ・状態管理を1つのフックへ抽出したもの。4つとも
// 「locationReadyになるまで待ち、location変更のたびに再フェッチする」という同じ形の
// effectを持ち、警告バッジ3種は失敗時も例外を投げず「警告なし」（null/空配列）として
// backend契約どおり静かに扱う点まで共通のため、1フックにまとめてある。
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getAmedasObservation,
  getCurrentWeather,
  getFloodForecasts,
  getWbgtStatus,
  getWeatherWarnings,
} from "@/services/weatherApi";
import type { Coordinates } from "@/types/route";
import type { AmedasObservation, FloodForecasts, WbgtStatus, WeatherConditions, WeatherWarnings } from "@/types/weather";
import type { WarningBadgeItem } from "@/components/WarningBadge/WarningBadge";

export interface UseWeatherConditionsResult {
  /** 今日の見通し（TodayOutlook向け）。Open-Meteoの予報値（日次集計・weather_code・
   * UV指数等）で、常設ヘッダーはこれを参照しない（常設エリアは実測値、今日の見通しは
   * 予測値という方針分離）。 */
  weather: WeatherConditions | null;
  weatherLoading: boolean;
  weatherError: string | null;
  /** 最寄りアメダス観測所の実測値（WeatherPanel＝常設ヘッダー向け）。Open-Meteoの成否・
   * 速度から独立してフェッチする。 */
  amedas: AmedasObservation | null;
  amedasLoading: boolean;
  amedasError: string | null;
  /** JMA警報・注意報・WBGT・河川氾濫予報を統合したバッジ一覧（WarningBadgeList向け）。 */
  warningBadgeItems: WarningBadgeItem[];
}

/** 現在地の天候・警告バッジ3種のフェッチ・状態管理。locationReadyが
 * trueになるまで待ち、その後はlocationが変わるたびに再フェッチする（マウント直後は
 * DEFAULT_LOCATION、Geolocationが成功すると実際の現在地でも1回走る、useLocation.ts参照）。
 * 各フェッチはリクエストごとに連番を振り、「一番最後に投げたリクエストの結果か」を
 * 確認してから反映する（古い応答が新しい応答を上書きしないようにする）。 */
export function useWeatherConditions(location: Coordinates, locationReady: boolean): UseWeatherConditionsResult {
  const [weather, setWeather] = useState<WeatherConditions | null>(null);
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [weatherError, setWeatherError] = useState<string | null>(null);

  const latestWeatherRequestId = useRef(0);
  const fetchWeatherFor = useCallback((next: Coordinates) => {
    const requestId = ++latestWeatherRequestId.current;
    setWeatherLoading(true);
    setWeatherError(null);
    getCurrentWeather(next)
      .then((conditions) => {
        if (requestId !== latestWeatherRequestId.current) return;
        setWeather(conditions);
      })
      .catch((error: unknown) => {
        if (requestId !== latestWeatherRequestId.current) return;
        setWeatherError(error instanceof Error ? error.message : "不明なエラーが発生しました");
      })
      .finally(() => {
        if (requestId !== latestWeatherRequestId.current) return;
        setWeatherLoading(false);
      });
  }, []);

  useEffect(() => {
    if (!locationReady) return;
    Promise.resolve().then(() => fetchWeatherFor(location));
  }, [locationReady, location, fetchWeatherFor]);

  // 最寄りアメダス観測所の実測値。weather（Open-Meteo）とは
  // 独立したフェッチ・状態にすることで、常設ヘッダーの表示がOpen-Meteoの障害・遅延から
  // 影響を受けないようにする。
  const [amedas, setAmedas] = useState<AmedasObservation | null>(null);
  const [amedasLoading, setAmedasLoading] = useState(false);
  const [amedasError, setAmedasError] = useState<string | null>(null);

  const latestAmedasRequestId = useRef(0);
  const fetchAmedasFor = useCallback((next: Coordinates) => {
    const requestId = ++latestAmedasRequestId.current;
    setAmedasLoading(true);
    setAmedasError(null);
    getAmedasObservation(next)
      .then((observation) => {
        if (requestId !== latestAmedasRequestId.current) return;
        setAmedas(observation);
      })
      .catch((error: unknown) => {
        if (requestId !== latestAmedasRequestId.current) return;
        setAmedasError(error instanceof Error ? error.message : "不明なエラーが発生しました");
      })
      .finally(() => {
        if (requestId !== latestAmedasRequestId.current) return;
        setAmedasLoading(false);
      });
  }, []);

  useEffect(() => {
    if (!locationReady) return;
    Promise.resolve().then(() => fetchAmedasFor(location));
  }, [locationReady, location, fetchAmedasFor]);

  // 警報・注意報バッジ。通信エラー時は例外を投げるだけで、警報なし
  // （空配列）として静かに扱う（バックエンド自体が失敗時に空warningsを返す契約のため、
  // これは主にネットワーク到達不能等の場合）。
  const [weatherWarnings, setWeatherWarnings] = useState<WeatherWarnings | null>(null);
  const latestWarningsRequestId = useRef(0);
  const fetchWarningsFor = useCallback((next: Coordinates) => {
    const requestId = ++latestWarningsRequestId.current;
    getWeatherWarnings(next)
      .then((result) => {
        if (requestId !== latestWarningsRequestId.current) return;
        setWeatherWarnings(result);
      })
      .catch(() => {
        if (requestId !== latestWarningsRequestId.current) return;
        setWeatherWarnings(null);
      });
  }, []);

  useEffect(() => {
    if (!locationReady) return;
    Promise.resolve().then(() => fetchWarningsFor(location));
  }, [locationReady, location, fetchWarningsFor]);

  // WBGT警告バッジ。提供期間外（11〜3月）・取得失敗・「ほぼ安全」の
  // いずれもbackend契約どおりlevel=nullとして静かに扱う。
  const [wbgtStatus, setWbgtStatus] = useState<WbgtStatus | null>(null);
  const latestWbgtRequestId = useRef(0);
  const fetchWbgtFor = useCallback((next: Coordinates) => {
    const requestId = ++latestWbgtRequestId.current;
    getWbgtStatus(next)
      .then((result) => {
        if (requestId !== latestWbgtRequestId.current) return;
        setWbgtStatus(result);
      })
      .catch(() => {
        if (requestId !== latestWbgtRequestId.current) return;
        setWbgtStatus(null);
      });
  }, []);

  useEffect(() => {
    if (!locationReady) return;
    Promise.resolve().then(() => fetchWbgtFor(location));
  }, [locationReady, location, fetchWbgtFor]);

  // 河川氾濫予報バッジ。他の警告バッジと同じ「取得失敗・対象河川なしは
  // forecasts=[]として静かに扱う」方式。
  const [floodForecasts, setFloodForecasts] = useState<FloodForecasts | null>(null);
  const latestFloodRequestId = useRef(0);
  const fetchFloodForecastsFor = useCallback((next: Coordinates) => {
    const requestId = ++latestFloodRequestId.current;
    getFloodForecasts(next)
      .then((result) => {
        if (requestId !== latestFloodRequestId.current) return;
        setFloodForecasts(result);
      })
      .catch(() => {
        if (requestId !== latestFloodRequestId.current) return;
        setFloodForecasts(null);
      });
  }, []);

  useEffect(() => {
    if (!locationReady) return;
    Promise.resolve().then(() => fetchFloodForecastsFor(location));
  }, [locationReady, location, fetchFloodForecastsFor]);

  const warningBadgeItems = useMemo<WarningBadgeItem[]>(() => {
    const jmaItems: WarningBadgeItem[] = weatherWarnings
      ? weatherWarnings.warnings.map((warning) => ({
          id: warning.code,
          label: warning.name,
          level: warning.level as WarningBadgeItem["level"],
          source: "jma",
          title: [
            warning.additions.length > 0 ? `付随事項: ${warning.additions.join("・")}` : null,
            "取得できない場合は警報が出ていてもバッジが表示されないことがあります",
          ]
            .filter(Boolean)
            .join(" / "),
        }))
      : [];
    // WBGTはlevelがnull（提供期間外・取得失敗・「ほぼ安全」のいずれか）の間は表示しない
    // （JMA警報が0件の場合と同じ「無ければ何も出ない」挙動）。
    const wbgtItem: WarningBadgeItem[] =
      wbgtStatus?.level && wbgtStatus.value != null
        ? [
            {
              id: "wbgt",
              label: `暑さ指数${wbgtStatus.label ?? ""}`,
              level: wbgtStatus.level as WarningBadgeItem["level"],
              source: "wbgt",
              title: `暑さ指数 ${wbgtStatus.value.toFixed(1)} / 取得できない場合は警戒レベルに関わらずバッジが表示されないことがあります`,
            },
          ]
        : [];
    // 河川氾濫予報（T212）。対象河川が無い/取得失敗の間はforecasts=[]のため何も出ない。
    const floodItems: WarningBadgeItem[] = (floodForecasts?.forecasts ?? []).map((forecast) => ({
      id: `flood-${forecast.river_code}`,
      label: forecast.label,
      level: forecast.badge_level as WarningBadgeItem["level"],
      source: "flood",
      title: `${forecast.condition} / 取得できない場合は氾濫予報が出ていてもバッジが表示されないことがあります`,
    }));
    return [...jmaItems, ...wbgtItem, ...floodItems];
  }, [weatherWarnings, wbgtStatus, floodForecasts]);

  return {
    weather,
    weatherLoading,
    weatherError,
    amedas,
    amedasLoading,
    amedasError,
    warningBadgeItems,
  };
}
