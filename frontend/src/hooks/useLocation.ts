"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Coordinates, LocationSource } from "@/types/route";

// 開発時の初期地点フォールバック: 東京都北区・王子駅付近
export const DEFAULT_LOCATION: Coordinates = { latitude: 35.7597, longitude: 139.7387 };
const GEOLOCATION_TIMEOUT_MS = 8000;

export interface UseLocationResult {
  location: Coordinates;
  locationSource: LocationSource;
  // マウント時の自動取得（成功・失敗・API非対応のいずれか）が確定したかどうか。
  // page.tsxの天候・警報等のフェッチが、DEFAULT_LOCATIONぶんの使い捨てリクエストを
  // 発行せず「確定した1つの地点」だけで済むよう待ち合わせるために使う（改善計画、
  // 実機フィードバック「天候がすぐ出てその後リフレッシュされる＝2回問い合わせ」対応）。
  locationReady: boolean;
  locating: boolean;
  locateError: string | null;
  handleLocateMe: () => void;
  /** 改善計画T366（T372で地図タップからドラッグ&ドロップへ再設計）: 出発地点マーカーを
   * ドラッグ&ドロップで手動指定する（MapView.tsx: dragendハンドラから呼ばれる）。
   * locationSourceを"manual"にし、まだ解決していないマウント時の自動取得や進行中の
   * handleLocateMe呼び出しが後から上書きしないようリクエストIDを無効化する
   * （handleLocateMeと同じ「後発の明示操作を優先する」パターン）。 */
  setManualLocation: (point: Coordinates) => void;
}

// 位置情報の取得・保持を一箇所に集約するフック（マウント時の自動取得／地図上の「現在地に
// 移動」ボタンからの再取得の2経路をまとめる。手動緯度経度入力はモバイル実機フィードバックで
// 不要と判断し撤去済み、docs/improvement-plan.md T35）。
//
// マウント時取得（最大8秒かかりうる）とボタンからの取得は非同期に並走しうるため、後から
// 発行したリクエストの結果を、先に発行したが遅れて返ってきたリクエストの結果が上書きして
// しまわないよう、リクエストごとに連番を振り「一番最後に発行したリクエストの結果か」を
// 確認してから反映する（page.tsx側のfetchWeatherForで使っているのと同じ手法）。
export function useLocation(): UseLocationResult {
  const [location, setLocation] = useState<Coordinates>(DEFAULT_LOCATION);
  const [locationSource, setLocationSource] = useState<LocationSource>("default");
  const [locationReady, setLocationReady] = useState(false);
  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState<string | null>(null);

  const latestGeolocationRequestId = useRef(0);

  // 現在地取得（失敗時は王子付近のデフォルト座標のまま。エラー表示はしない）。
  // 成功・失敗・API非対応のいずれの経路でも必ずlocationReadyをtrueにする
  // （呼び出し側がこのフラグだけを見て「もう待つ必要は無い」と判断できるようにする）。
  useEffect(() => {
    if (!navigator.geolocation) {
      // effect本体からの直接同期setState呼び出しを避け、マイクロタスク経由で実行する
      // （react-hooks/set-state-in-effect対策、page.tsxのfetchWeatherForと同じ流儀）。
      Promise.resolve().then(() => setLocationReady(true));
      return;
    }

    const requestId = ++latestGeolocationRequestId.current;
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (requestId !== latestGeolocationRequestId.current) return;
        setLocation({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        });
        setLocationSource("geolocation");
        setLocationReady(true);
      },
      () => {
        if (requestId !== latestGeolocationRequestId.current) return;
        // no-op削除（デッドコード監査、2026-08-25）: ここに来る時点でlocationSourceは
        // 初期値"default"のまま変化しえない（成功コールバックとは排他、かつ上のrequestId
        // チェックによりhandleLocateMe由来の後発リクエストに追い越されていた場合は既に
        // returnしている）ため、setLocationSource("default")は常にno-opだった。
        setLocationReady(true);
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

  // 改善計画T366（T372でドラッグ&ドロップへ再設計）: 出発地点の手動指定。マウント時の
  // 自動取得・handleLocateMeによる再取得は非同期のため、手動指定した後にそれらが遅れて
  // 解決して上書きしてしまわないよう、handleLocateMeと同じリクエストID無効化を行う。
  const setManualLocation = useCallback((point: Coordinates) => {
    latestGeolocationRequestId.current += 1;
    setLocation(point);
    setLocationSource("manual");
    setLocating(false);
    setLocateError(null);
  }, []);

  return {
    location,
    locationSource,
    locationReady,
    locating,
    locateError,
    handleLocateMe,
    setManualLocation,
  };
}
