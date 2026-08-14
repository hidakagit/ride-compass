"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Coordinates, LocationSource } from "@/types/route";

// 開発時の初期地点フォールバック: 東京都北区・王子駅付近
export const DEFAULT_LOCATION: Coordinates = { latitude: 35.7597, longitude: 139.7387 };
const GEOLOCATION_TIMEOUT_MS = 8000;

export interface UseLocationResult {
  location: Coordinates;
  locationSource: LocationSource;
  manualLat: string;
  manualLng: string;
  showManualInput: boolean;
  locating: boolean;
  locateError: string | null;
  manualLocationError: string | null;
  setManualLat: (value: string) => void;
  setManualLng: (value: string) => void;
  toggleManualInput: () => void;
  handleManualSubmit: (event: React.FormEvent) => void;
  handleLocateMe: () => void;
}

// 位置情報の取得・保持を一箇所に集約するフック（マウント時の自動取得／地図上の「現在地に
// 移動」ボタンからの再取得／手動緯度経度入力の3経路をまとめる）。
//
// マウント時取得（最大8秒かかりうる）とボタンからの取得は非同期に並走しうるため、後から
// 発行したリクエストの結果を、先に発行したが遅れて返ってきたリクエストの結果が上書きして
// しまわないよう、リクエストごとに連番を振り「一番最後に発行したリクエストの結果か」を
// 確認してから反映する（page.tsx側のfetchWeatherForで使っているのと同じ手法）。
export function useLocation(): UseLocationResult {
  const [location, setLocation] = useState<Coordinates>(DEFAULT_LOCATION);
  const [locationSource, setLocationSource] = useState<LocationSource>("default");
  const [manualLat, setManualLat] = useState(String(DEFAULT_LOCATION.latitude));
  const [manualLng, setManualLng] = useState(String(DEFAULT_LOCATION.longitude));
  const [showManualInput, setShowManualInput] = useState(false);
  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState<string | null>(null);
  const [manualLocationError, setManualLocationError] = useState<string | null>(null);

  const latestGeolocationRequestId = useRef(0);

  // 現在地取得（失敗時は王子付近のデフォルト座標のまま。エラー表示はしない）
  useEffect(() => {
    if (!navigator.geolocation) return;

    const requestId = ++latestGeolocationRequestId.current;
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (requestId !== latestGeolocationRequestId.current) return;
        setLocation({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        });
        setLocationSource("geolocation");
      },
      () => {
        if (requestId !== latestGeolocationRequestId.current) return;
        setLocationSource("default");
      },
      { timeout: GEOLOCATION_TIMEOUT_MS }
    );
  }, []);

  // 地図上の「現在地に移動」ボタン用。マウント時の自動取得とは別に、ユーザーが明示的に
  // 押した操作として都度取得し直す（位置情報の許可をマウント後に与えた場合の再取得や、
  // 地図を移動した後に現在地へ戻す操作を想定）。失敗時はエラーメッセージを表示する
  // （マウント時の無言フォールバックとは異なり、ユーザー操作への直接の応答のため）。
  const handleLocateMe = useCallback(() => {
    if (!navigator.geolocation) {
      setLocateError("この端末では位置情報を取得できません。");
      return;
    }
    const requestId = ++latestGeolocationRequestId.current;
    setLocating(true);
    setLocateError(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (requestId !== latestGeolocationRequestId.current) return;
        setLocation({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        });
        setLocationSource("geolocation");
        setLocating(false);
      },
      () => {
        if (requestId !== latestGeolocationRequestId.current) return;
        setLocateError("現在地を取得できませんでした。位置情報の利用が許可されているかご確認ください。");
        setLocating(false);
      },
      { timeout: GEOLOCATION_TIMEOUT_MS }
    );
  }, []);

  const toggleManualInput = useCallback(() => setShowManualInput((v) => !v), []);

  const handleManualSubmit = useCallback(
    (event: React.FormEvent) => {
      event.preventDefault();
      // Number("")は0を返しNaNにならないため、空欄のまま送信すると気づかず(0,0)
      // （ギニア湾沖）へ切り替わっていた。trim()で空欄を先に弾き、範囲外の値
      // （緯度±90度・経度±180度を超える値）も明示的にエラー表示する。
      if (manualLat.trim() === "" || manualLng.trim() === "") {
        setManualLocationError("緯度・経度を入力してください。");
        return;
      }
      const latitude = Number(manualLat);
      const longitude = Number(manualLng);
      if (Number.isNaN(latitude) || Number.isNaN(longitude)) {
        setManualLocationError("緯度・経度は数値で入力してください。");
        return;
      }
      if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
        setManualLocationError("緯度は-90〜90、経度は-180〜180の範囲で入力してください。");
        return;
      }
      setManualLocationError(null);
      setLocation({ latitude, longitude });
      setLocationSource("manual");
    },
    [manualLat, manualLng]
  );

  return {
    location,
    locationSource,
    manualLat,
    manualLng,
    showManualInput,
    locating,
    locateError,
    manualLocationError,
    setManualLat,
    setManualLng,
    toggleManualInput,
    handleManualSubmit,
    handleLocateMe,
  };
}
