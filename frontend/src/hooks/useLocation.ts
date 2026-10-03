"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FetchFailure } from "@/types/fetchFailure";
import type { Coordinates, LocationSource } from "@/types/route";

// 位置が取れないときの初期地点（東京都北区・王子駅付近）。ここからはルートを生成せず、天候・警報も取らない。
const DEFAULT_LOCATION: Coordinates = { latitude: 35.7597, longitude: 139.7387 };
const GEOLOCATION_TIMEOUT_MS = 8000;

interface UseLocationResult {
  location: Coordinates;
  locationSource: LocationSource;
  /** 位置が分かっているか（取れたか、手で置いたか）。分からない間の`location`は初期地点で、利用者のいる場所と関係が無い。 */
  locationKnown: boolean;
  /** 位置が分からないことの常設ヘッダーの印の項目。最初の取得（自動取得か、それを追い越した取り直し）が決着するまでは
   * 出さない（許可ダイアログへの応答はどんな長さの待ちも超えうるので、時間で待たない）。 */
  locationFailure: FetchFailure | null;
  locating: boolean;
  locateError: string | null;
  handleLocateMe: () => void;
  /** 出発地点を手で決める（マーカーのドラッグ）。まだ返っていない自動取得が後から上書きしないようにする。 */
  setManualLocation: (point: Coordinates) => void;
}

/** 位置の取得と保持。マウント時の自動取得と「現在地に移動」の取り直しは並走しうるので、最後に出した要求の結果
 * だけを反映する。 */
export function useLocation(): UseLocationResult {
  const [location, setLocation] = useState<Coordinates>(DEFAULT_LOCATION);
  const [locationSource, setLocationSource] = useState<LocationSource>("default");
  const [locationReady, setLocationReady] = useState(false);
  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState<string | null>(null);

  const latestRequestId = useRef(0);

  // 追い越された要求の結果は捨てるので、決着は自動取得か取り直しかによらず、最後の要求で立てる。
  const requestPosition = useCallback((onSettled: (ok: boolean) => void) => {
    const requestId = ++latestRequestId.current;
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (requestId !== latestRequestId.current) return;
        setLocation({ latitude: position.coords.latitude, longitude: position.coords.longitude });
        setLocationSource("geolocation");
        setLocationReady(true);
        onSettled(true);
      },
      () => {
        if (requestId !== latestRequestId.current) return;
        setLocationReady(true);
        onSettled(false);
      },
      { timeout: GEOLOCATION_TIMEOUT_MS },
    );
  }, []);

  // 自動取得の失敗は文を出さず、初期地点のまま`locationKnown`が偽で残る（読み手はそれで仮の地点と分かる）。
  useEffect(() => {
    if (!navigator.geolocation) {
      // effectの中で同期にsetStateしない（react-hooks/set-state-in-effect）。
      Promise.resolve().then(() => setLocationReady(true));
      return;
    }
    requestPosition(() => {});
  }, [requestPosition]);

  // 利用者が押した取り直しには、失敗を知らせる。
  const handleLocateMe = useCallback(() => {
    if (!navigator.geolocation) {
      setLocateError("この端末では位置情報を取得できません。");
      return;
    }
    setLocating(true);
    setLocateError(null);
    requestPosition((ok) => {
      if (!ok) setLocateError("現在地を取得できませんでした。位置情報の利用が許可されているかご確認ください。");
      setLocating(false);
    });
  }, [requestPosition]);

  const setManualLocation = useCallback((point: Coordinates) => {
    latestRequestId.current += 1;
    setLocation(point);
    setLocationSource("manual");
    setLocating(false);
    setLocateError(null);
  }, []);

  const locationKnown = locationSource !== "default";
  const locationFailure = useMemo<FetchFailure | null>(
    () =>
      locationReady && !locationKnown
        ? {
            id: "location",
            label: "現在地",
            effect:
              "現在地が分からないため、天候・警報を出していません。位置情報を許可するか、「ルート設定」の出発地の「地図で選ぶ」を押して地図をタップしてください。",
            onRetry: handleLocateMe,
          }
        : null,
    [locationReady, locationKnown, handleLocateMe],
  );

  return {
    location,
    locationSource,
    locationKnown,
    locationFailure,
    locating,
    locateError,
    handleLocateMe,
    setManualLocation,
  };
}
