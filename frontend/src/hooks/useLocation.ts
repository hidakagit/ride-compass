"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Coordinates, LocationSource } from "@/types/route";

// 位置が取れないときの初期地点（東京都北区・王子駅付近）。
const DEFAULT_LOCATION: Coordinates = { latitude: 35.7597, longitude: 139.7387 };
const GEOLOCATION_TIMEOUT_MS = 8000;

interface UseLocationResult {
  location: Coordinates;
  locationSource: LocationSource;
  /** マウント時の自動取得が（成功・失敗・非対応のどれかで）決着したか。天候等の取得はこれを待ち、初期地点ぶんの
   * 使い捨ての問い合わせをしない（許可ダイアログへの応答はどんな長さの待ちも超えうるので、時間で待たない）。 */
  locationReady: boolean;
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

  const requestPosition = useCallback((onSettled: (ok: boolean) => void) => {
    const requestId = ++latestRequestId.current;
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (requestId !== latestRequestId.current) return;
        setLocation({ latitude: position.coords.latitude, longitude: position.coords.longitude });
        setLocationSource("geolocation");
        onSettled(true);
      },
      () => {
        if (requestId !== latestRequestId.current) return;
        onSettled(false);
      },
      { timeout: GEOLOCATION_TIMEOUT_MS },
    );
  }, []);

  // 自動取得は失敗しても初期地点のまま黙って進む。
  useEffect(() => {
    if (!navigator.geolocation) {
      // effectの中で同期にsetStateしない（react-hooks/set-state-in-effect）。
      Promise.resolve().then(() => setLocationReady(true));
      return;
    }
    requestPosition(() => setLocationReady(true));
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

  return { location, locationSource, locationReady, locating, locateError, handleLocateMe, setManualLocation };
}
