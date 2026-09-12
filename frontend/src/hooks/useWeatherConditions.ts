"use client";

// 現在地の天候（WeatherPanel向け）と3種の警告バッジ（JMA警報・注意報／WBGT／
// 河川氾濫予報）のフェッチ・状態管理を1つのフックへ抽出したもの。4つとも
// 「locationReadyになるまで待ち、location変更のたびに再フェッチする」という同じ形の
// effectを持ち、警告バッジ3種は失敗時も例外を投げず「警告なし」（null/空配列）として
// backend契約どおり静かに扱う点まで共通のため、1フックにまとめてある。
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
import type { WarningBadgeItem } from "@/components/WarningBadge/WarningBadge";

export interface UseWeatherConditionsResult {
  /** 今日の見通し（TodayOutlook向け）。気象庁MSMの予報値（日次集計・weather_code・
   * UV指数等）で、常設ヘッダーはこれを参照しない（常設エリアは実測値、今日の見通しは
   * 予測値という方針分離）。 */
  weather: WeatherConditions | null;
  weatherLoading: boolean;
  weatherError: string | null;
  /** 最寄りアメダス観測所の実測値（WeatherPanel＝常設ヘッダー向け）。予報側の成否・
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
interface LocationFetchState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

// 取得しっぱなしにせず一定間隔で取り直す。アメダスは10分ごとの観測値で、警報・注意報は
// 随時更新されるため、開いたままの画面が古い値のまま固定されるのを防ぐ。一度きりだと
// 通信の一時的な失敗がそのセッション中ずっと表示に残り続けることにもなる。
const WEATHER_REFRESH_INTERVAL_MS = 10 * 60 * 1000;

/** 「locationReadyになるまで待ち、locationが変わるたびに再フェッチし、**最後に投げた
 * リクエストの結果だけ**を反映する」という共通形。本ファイルの5つのフェッチが同じ骨格を
 * 持つため1箇所へ集約する（連番ガードを写経すると、1つだけガードを書き落としても
 * 「稀に古い応答が新しい応答を上書きする」という再現しにくい形でしか現れない）。
 *
 * 失敗しても直前に取得済みのデータは保持する（取得済みの表示を消さず、`error`を添えて
 * 呼び出し側に判断させる）。失敗時に表示ごと消したい呼び出し元は`error`を見て自分で
 * nullへ倒す。 */
function useLocationFetch<T>(
  fetcher: (location: Coordinates) => Promise<T>,
  location: Coordinates,
  locationReady: boolean,
): LocationFetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latestRequestId = useRef(0);

  // fetcherは呼び出し側でモジュールスコープの関数を渡す想定（毎レンダー新しい関数を
  // 渡すと再フェッチが止まらなくなる）。
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);

  useEffect(() => {
    if (!locationReady) return;
    let disposed = false;
    const run = () => {
      const requestId = ++latestRequestId.current;
      setLoading(true);
      fetcherRef.current(location)
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
    // setState呼び出しを含むため、effect本体からの直接同期呼び出しを避けてマイクロタスク
    // 経由で実行する（他のフックと同じreact-hooks/set-state-in-effect対策）。
    Promise.resolve().then(() => {
      if (!disposed) run();
    });
    const timer = setInterval(run, WEATHER_REFRESH_INTERVAL_MS);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [locationReady, location]);

  return { data, loading, error };
}

export function useWeatherConditions(location: Coordinates, locationReady: boolean): UseWeatherConditionsResult {
  // 今日の見通し（MSM予報）。取得に失敗しても直前の値は残し、errorを添えて表示側
  // （TodayOutlook）に判断させる。
  const weather = useLocationFetch(getCurrentWeather, location, locationReady);
  // 最寄りアメダス観測所の実測値。weather（MSM予報）とは独立したフェッチ・状態にすることで、
  // 常設ヘッダーの表示が予報側の障害・遅延から影響を受けないようにする。
  const amedas = useLocationFetch(getAmedasObservation, location, locationReady);

  // 警告バッジ3種（JMA警報・注意報／WBGT／河川氾濫予報）。いずれも取得失敗を例外として
  // 見せず「警告なし」として静かに扱う（backend自体が失敗時に空の結果を返す契約のため、
  // ここへ来るのは主にネットワーク到達不能等）。表示側へは失敗時にnullを渡す。
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
    // WBGTはlevelがnull（提供期間外・取得失敗・「ほぼ安全」のいずれか）の間は表示しない
    // （JMA警報が0件の場合と同じ「無ければ何も出ない」挙動）。
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
    // 河川氾濫予報（T212）。対象河川が無い/取得失敗の間はforecasts=[]のため何も出ない。
    const floodItems: WarningBadgeItem[] = (floodForecasts?.forecasts ?? []).map((forecast) => ({
      id: `flood-${forecast.river_code}`,
      label: forecast.label,
      level: forecast.badge_level,
      source: "flood",
      title: `${forecast.condition} / 取得できない場合は氾濫予報が出ていてもバッジが表示されないことがあります`,
    }));
    return [...jmaItems, ...wbgtItem, ...floodItems];
  }, [weatherWarnings, wbgtStatus, floodForecasts]);

  return {
    weather: weather.data,
    weatherLoading: weather.loading,
    weatherError: weather.error,
    amedas: amedas.data,
    amedasLoading: amedas.loading,
    amedasError: amedas.error,
    warningBadgeItems,
  };
}
