"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import MapView from "@/components/Map/MapView";
import BackendStatus from "@/components/BackendStatus";
import DebugPanel from "@/components/DebugPanel/DebugPanel";
import DebugConsole, { DEBUG_CONSOLE_MAX_HEIGHT_PX } from "@/components/DebugConsole/DebugConsole";
import LocationControl from "@/components/LocationControl/LocationControl";
import MapOverlayControls from "@/components/MapOverlayControls/MapOverlayControls";
import {
  DEFAULT_ROAD_STYLE_MODE_ID,
  isRoadStyleModeId,
  type RoadStyleModeId,
} from "@/components/Map/roadStyleModes";
import {
  DEFAULT_ROUTE_STYLE_MODE_ID,
  isRouteStyleModeId,
  type RouteStyleModeId,
} from "@/components/Map/routeStyleModes";
import RouteForm from "@/components/RouteForm/RouteForm";
import RouteList from "@/components/RouteList/RouteList";
import WeatherPanel from "@/components/WeatherPanel/WeatherPanel";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useIsomorphicLayoutEffect } from "@/hooks/useIsomorphicLayoutEffect";
import { useLocation } from "@/hooks/useLocation";
import { generateRoutes } from "@/services/routeApi";
import { getCurrentWeather } from "@/services/weatherApi";
import type { Coordinates, RouteCandidate } from "@/types/route";
import type { WeatherConditions } from "@/types/weather";
import styles from "./page.module.css";

const DISTANCE_TOLERANCE_KM = 5;

// 色分けモード（路面・ルート）の保存先。プライベートブラウジング等でlocalStorageが
// 使えない環境があるため、読み書きとも失敗はデフォルトモードへのフォールバックとして
// 握りつぶす。
const ROAD_STYLE_MODE_STORAGE_KEY = "ridecompass:road-style-mode";
const ROUTE_STYLE_MODE_STORAGE_KEY = "ridecompass:route-style-mode";

function loadStoredStyleMode<T extends string>(storageKey: string, isValid: (v: string | null) => v is T, fallback: T): T {
  try {
    const stored = window.localStorage.getItem(storageKey);
    if (isValid(stored)) return stored;
  } catch {
    // 読み出し不可はデフォルト扱い
  }
  return fallback;
}

// 「どのモードでも非表示カテゴリ無し」を表す共通の空配列。useStateの外に置いて参照を
// 固定し、MapView側のエフェクト依存（hidden*LegendKeys）が毎レンダーで発火しないようにする。
const NO_HIDDEN_LEGEND_KEYS: string[] = [];

// 現在地に移動ボタン・そのエラー表示の、地図右下からの間隔（px）。
// デバッグモードOFF時はMapLibreの既定のアトリビューション表示（右下）と重ならない程度の
// 間隔（rem指定、既存の見た目を維持）、ON時はDebugConsole（画面下部に最大
// DEBUG_CONSOLE_MAX_HEIGHT_PX分重なる）の上に出るようpx単位で計算する。
const LOCATE_BUTTON_HEIGHT_PX = 44;
const LOCATE_BUTTON_GAP_PX = 12;

export default function Home() {
  const {
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
  } = useLocation();

  const [routes, setRoutes] = useState<RouteCandidate[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [weather, setWeather] = useState<WeatherConditions | null>(null);
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [weatherError, setWeatherError] = useState<string | null>(null);

  const [showElevation, setShowElevation] = useState(false);
  const [showRoad, setShowRoad] = useState(false);
  const [roadStyleModeId, setRoadStyleModeId] = useState<RoadStyleModeId>(DEFAULT_ROAD_STYLE_MODE_ID);
  const [routeLayerOn, setRouteLayerOn] = useState(true);
  const [routeStyleModeId, setRouteStyleModeId] = useState<RouteStyleModeId>(DEFAULT_ROUTE_STYLE_MODE_ID);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [regionZoomTooWide, setRegionZoomTooWide] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);

  const toggleButtonRef = useRef<HTMLButtonElement>(null);
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);
  const debugEnabled = useDebugEnabled();

  const selectedCandidate = routes.find((r) => r.id === selectedRouteId) ?? null;
  const hasDetail = !!selectedCandidate?.segments && selectedCandidate.segments.length > 0;

  // スマホ幅では地図を常に主役として見せたいため、初回にモバイル判定された時だけ
  // サイドバーを自動的に閉じる（以降はユーザーの開閉操作を尊重し、リサイズのたびに
  // 勝手に閉じ直したりはしない）。
  // useIsomorphicLayoutEffectを使うのは、useIsMobile自身のisMobile判定も同じ理由で
  // レイアウトエフェクト化しているため（ちらつき防止）。ここも通常のuseEffectのままだと、
  // isMobileがペイント前に確定してもこちらの折りたたみ反映がペイント後にずれ込み、
  // 結局モバイル初回表示でサイドバー全開のドロワーが一瞬見えてしまう。
  const isMobile = useIsMobile();
  const appliedMobileDefaultRef = useRef(false);
  useIsomorphicLayoutEffect(() => {
    if (isMobile && !appliedMobileDefaultRef.current) {
      appliedMobileDefaultRef.current = true;
      setSidebarCollapsed(true);
    }
  }, [isMobile]);

  // 前回選んだ色分けモード（路面・ルート）を復元する。useStateの初期化子でlocalStorageを
  // 読むとSSR（プリレンダー）時のHTMLとハイドレーション結果がずれるため、マウント後に読む。
  // レイアウトエフェクトなのはサイドバー折りたたみと同じちらつき防止の理由。
  useIsomorphicLayoutEffect(() => {
    setRoadStyleModeId(loadStoredStyleMode(ROAD_STYLE_MODE_STORAGE_KEY, isRoadStyleModeId, DEFAULT_ROAD_STYLE_MODE_ID));
    setRouteStyleModeId(
      loadStoredStyleMode(ROUTE_STYLE_MODE_STORAGE_KEY, isRouteStyleModeId, DEFAULT_ROUTE_STYLE_MODE_ID),
    );
  }, []);

  const handleRoadStyleModeChange = useCallback((id: RoadStyleModeId) => {
    setRoadStyleModeId(id);
    try {
      window.localStorage.setItem(ROAD_STYLE_MODE_STORAGE_KEY, id);
    } catch {
      // 保存不可でも選択自体はこのセッション内で有効
    }
  }, []);

  const handleRouteStyleModeChange = useCallback((id: RouteStyleModeId) => {
    setRouteStyleModeId(id);
    try {
      window.localStorage.setItem(ROUTE_STYLE_MODE_STORAGE_KEY, id);
    } catch {
      // 保存不可でも選択自体はこのセッション内で有効
    }
  }, []);

  // 凡例タップで非表示にしたカテゴリ（モード別に保持。モードを行き来しても各モードの
  // 取捨選択が残る）。路面モードとルートモードのIDは互いに重複しないため1つのレコードで
  // 両系統を管理できる。その場の絞り込み操作なのでlocalStorageへは保存しない。
  const [hiddenLegendKeysByMode, setHiddenLegendKeysByMode] = useState<Record<string, string[]>>({});
  const hiddenRoadLegendKeys = hiddenLegendKeysByMode[roadStyleModeId] ?? NO_HIDDEN_LEGEND_KEYS;
  const hiddenRouteLegendKeys = hiddenLegendKeysByMode[routeStyleModeId] ?? NO_HIDDEN_LEGEND_KEYS;
  const toggleHiddenLegendKey = useCallback((modeId: string, key: string) => {
    setHiddenLegendKeysByMode((prev) => {
      const current = prev[modeId] ?? [];
      const next = current.includes(key) ? current.filter((k) => k !== key) : [...current, key];
      return { ...prev, [modeId]: next };
    });
  }, []);
  const handleRoadLegendToggle = useCallback(
    (key: string) => toggleHiddenLegendKey(roadStyleModeId, key),
    [roadStyleModeId, toggleHiddenLegendKey],
  );
  const handleRouteLegendToggle = useCallback(
    (key: string) => toggleHiddenLegendKey(routeStyleModeId, key),
    [routeStyleModeId, toggleHiddenLegendKey],
  );

  // モバイルのドロワーを閉じる共通処理。背景タップ・スワイプ・Escapeキーのいずれから
  // 閉じた場合も、フォーカスが失われたパネル内要素からトグルボタンへ戻す（キーボード/
  // スクリーンリーダー利用時に閉じた後の操作起点を見失わないようにするため）。
  const closeSidebar = useCallback(() => {
    setSidebarCollapsed(true);
    toggleButtonRef.current?.focus();
  }, []);

  // モバイルでドロワー展開中のみ、Escapeキーで閉じられるようにする
  useEffect(() => {
    if (!isMobile || sidebarCollapsed) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") closeSidebar();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isMobile, sidebarCollapsed, closeSidebar]);

  // モバイルでドロワー展開中のみ、左方向へのスワイプで閉じる。縦方向の移動量が大きい
  // 場合はパネル内リストのスクロール操作とみなして無視する。
  const SWIPE_CLOSE_THRESHOLD_PX = 60;
  function handleSidebarTouchStart(e: React.TouchEvent) {
    if (!isMobile || sidebarCollapsed) return;
    const touch = e.touches[0];
    touchStartRef.current = { x: touch.clientX, y: touch.clientY };
  }
  function handleSidebarTouchEnd(e: React.TouchEvent) {
    const start = touchStartRef.current;
    touchStartRef.current = null;
    if (!start || !isMobile || sidebarCollapsed) return;
    const touch = e.changedTouches[0];
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    if (dx < -SWIPE_CLOSE_THRESHOLD_PX && Math.abs(dx) > Math.abs(dy)) {
      closeSidebar();
    }
  }

  // 現在地が変わったらその地点の天候を取得（ルート生成時の風評価の起点にもなる）。
  // マウント直後はDEFAULT_LOCATIONで取得が走り、その直後にGeolocationが成功すると
  // 実際の現在地でも取得が走る。ネットワーク遅延次第で先に投げた方が後に返ってくることが
  // あるため、リクエストごとに連番を振り「一番最後に投げたリクエストの結果か」を確認してから
  // setWeatherする（古い応答が新しい応答を上書きしないようにする）。
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
    // fetchWeatherForはsetState呼び出しを含むため、effect本体からの直接同期呼び出しを避けて
    // マイクロタスク経由で実行する（react-hooks/set-state-in-effect対策）
    Promise.resolve().then(() => fetchWeatherFor(location));
  }, [location, fetchWeatherFor]);

  async function handleGenerate(distanceKm: number) {
    setLoading(true);
    setErrorMessage(null);
    try {
      const candidates = await generateRoutes({
        latitude: location.latitude,
        longitude: location.longitude,
        distance_km: distanceKm,
        distance_tolerance_km: DISTANCE_TOLERANCE_KM,
        route_type: "loop",
      });
      setRoutes(candidates);
      setSelectedRouteId(candidates[0]?.id ?? null);
      if (candidates.length === 0) {
        setErrorMessage("条件に合うルート候補が見つかりませんでした。距離を変えて試してください。");
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "不明なエラーが発生しました");
    } finally {
      setLoading(false);
    }
  }

  const locateButtonBottomPx = debugEnabled ? DEBUG_CONSOLE_MAX_HEIGHT_PX + LOCATE_BUTTON_GAP_PX : null;
  const locateErrorBottomPx = debugEnabled
    ? DEBUG_CONSOLE_MAX_HEIGHT_PX + LOCATE_BUTTON_GAP_PX + LOCATE_BUTTON_HEIGHT_PX + LOCATE_BUTTON_GAP_PX
    : null;
  const isDrawerOpen = isMobile && !sidebarCollapsed;

  return (
    <div className="app-shell">
      {isDrawerOpen && <div className="app-sidebar-backdrop" onClick={closeSidebar} aria-hidden="true" />}

      <aside
        className={`app-sidebar${sidebarCollapsed ? " is-collapsed" : ""}`}
        onTouchStart={handleSidebarTouchStart}
        onTouchEnd={handleSidebarTouchEnd}
        role={isDrawerOpen ? "dialog" : undefined}
        aria-modal={isDrawerOpen ? true : undefined}
        aria-label={isDrawerOpen ? "メニュー" : undefined}
      >
        <button
          ref={toggleButtonRef}
          type="button"
          onClick={() => setSidebarCollapsed((v) => !v)}
          aria-label={sidebarCollapsed ? "パネルを開く" : "パネルを閉じる"}
          className={styles.toggleButton}
        >
          {sidebarCollapsed ? "▶" : "◀"}
        </button>

        {!sidebarCollapsed && (
          <>
            <header>
              <h1 className={styles.title}>RideCompass</h1>
              <p className={styles.subtitle}>ロードバイク向け周回ルート生成アプリ（プロトタイプ）</p>
            </header>

            <BackendStatus />
            <DebugPanel />
            <WeatherPanel weather={weather} loading={weatherLoading} error={weatherError} />

            <LocationControl
              location={location}
              source={locationSource}
              manualLat={manualLat}
              manualLng={manualLng}
              showManualInput={showManualInput}
              manualLocationError={manualLocationError}
              onManualLatChange={setManualLat}
              onManualLngChange={setManualLng}
              onToggleManualInput={toggleManualInput}
              onManualSubmit={handleManualSubmit}
            />

            {/* ルート生成は「地図レイヤーだけ使いたい」用途では不要なため、折りたたみ
                （デフォルト閉）にして地図側の視界を優先する。候補一覧・エラーもルート生成の
                一部としてこの中にまとめる（レイヤーのON/OFFは地図上のMapOverlayControlsへ移動済み）。 */}
            <details className={styles.routeSection}>
              <summary className={styles.routeSectionSummary}>ルート生成</summary>
              <RouteForm onGenerate={handleGenerate} loading={loading} />
              {errorMessage && <p className={styles.errorMessage}>{errorMessage}</p>}
              <RouteList routes={routes} selectedRouteId={selectedRouteId} onSelect={setSelectedRouteId} />
            </details>

            {/* 基礎地図・路面タイルのキャッシュ更新は日常操作ではない運用ボタンのため最下部に置く */}
            <button type="button" onClick={() => setRefreshToken((v) => v + 1)} className={styles.refreshButton}>
              変わらないデータを更新
            </button>
          </>
        )}
      </aside>

      {/*
        inertは、モバイルでドロワーがrole="dialog" aria-modal="true"として開いている間、
        その裏に隠れているこのペイン（地図・現在地ボタン・DebugConsole）をフォーカス不能かつ
        スクリーンリーダーから見えない状態にする。これが無いと、キーボード操作でドロワー内の
        最後の要素からTabを送った際に、暗幕の下に隠れているはずのこのペイン内の要素（現在地
        ボタン等）へフォーカスが抜けてしまい、aria-modalの宣言と実際の挙動が食い違う。
      */}
      <div className={styles.mapPane} inert={isDrawerOpen}>
        <MapView
          routes={routes}
          selectedRouteId={selectedRouteId}
          location={location}
          showElevation={showElevation}
          showRoad={showRoad}
          roadStyleModeId={roadStyleModeId}
          hiddenRoadLegendKeys={hiddenRoadLegendKeys}
          routeLayerOn={routeLayerOn}
          routeStyleModeId={routeStyleModeId}
          hiddenRouteLegendKeys={hiddenRouteLegendKeys}
          onRegionZoomHintChange={setRegionZoomTooWide}
          refreshToken={refreshToken}
        />

        <MapOverlayControls
          showElevation={showElevation}
          onShowElevationToggle={setShowElevation}
          showRoad={showRoad}
          onShowRoadToggle={setShowRoad}
          roadStyleModeId={roadStyleModeId}
          onRoadStyleModeChange={handleRoadStyleModeChange}
          hiddenRoadLegendKeys={hiddenRoadLegendKeys}
          onRoadLegendToggle={handleRoadLegendToggle}
          routeLayerOn={routeLayerOn}
          onRouteLayerToggle={setRouteLayerOn}
          routeStyleModeId={routeStyleModeId}
          onRouteStyleModeChange={handleRouteStyleModeChange}
          hiddenRouteLegendKeys={hiddenRouteLegendKeys}
          onRouteLegendToggle={handleRouteLegendToggle}
          hasDetail={hasDetail}
          regionZoomTooWide={regionZoomTooWide}
        />

        <button
          type="button"
          onClick={handleLocateMe}
          disabled={locating}
          aria-label="現在地に移動"
          title="現在地に移動"
          className={locating ? `${styles.locateButton} ${styles.locateButtonBusy}` : styles.locateButton}
          style={locateButtonBottomPx != null ? { bottom: `${locateButtonBottomPx}px` } : undefined}
        >
          {locating ? (
            "…"
          ) : (
            // 以前はUnicode文字「◎」を使っていたが、Android Chrome実機では書体（Noto Sans）が
            // 中央のドットを描画せず単なる白丸に見える不具合が実機で確認されたため、フォントに
            // 依存しないSVGアイコン（十字線+中心ドット、地図アプリの現在地アイコンの定番形状）
            // に置き換えた。
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="12" r="3" fill="currentColor" />
              <path
                d="M12 2v3M12 19v3M2 12h3M19 12h3M12 6a6 6 0 1 0 0 12 6 6 0 0 0 0-12Z"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          )}
        </button>

        {locateError && (
          <p
            className={styles.locateError}
            style={locateErrorBottomPx != null ? { bottom: `${locateErrorBottomPx}px` } : undefined}
          >
            {locateError}
          </p>
        )}

        <DebugConsole />
      </div>
    </div>
  );
}
