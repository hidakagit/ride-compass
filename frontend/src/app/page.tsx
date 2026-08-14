"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapView from "@/components/Map/MapView";
import BackendStatus from "@/components/BackendStatus";
import DebugPanel from "@/components/DebugPanel/DebugPanel";
import DebugConsole, { DEBUG_CONSOLE_MAX_HEIGHT_PX } from "@/components/DebugConsole/DebugConsole";
import LocationControl from "@/components/LocationControl/LocationControl";
import MapOverlayControls from "@/components/MapOverlayControls/MapOverlayControls";
import MapLegendPanel from "@/components/MapLegendPanel/MapLegendPanel";
import { ROAD_FILTER_AXES, type RoadFilterAxisId } from "@/components/Map/roadFilterAxes";
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

// 色分けモード（ルート）の保存先。プライベートブラウジング等でlocalStorageが
// 使えない環境があるため、読み書きとも失敗はデフォルトモードへのフォールバックとして
// 握りつぶす。路面側は色分けモードを持たない（常に固定色。roadFilterAxes.ts参照）ため
// 対応する保存先は無い。
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

  // 前回選んだ色分けモード（ルート）を復元する。useStateの初期化子でlocalStorageを
  // 読むとSSR（プリレンダー）時のHTMLとハイドレーション結果がずれるため、マウント後に読む。
  // レイアウトエフェクトなのはサイドバー折りたたみと同じちらつき防止の理由。
  useIsomorphicLayoutEffect(() => {
    setRouteStyleModeId(
      loadStoredStyleMode(ROUTE_STYLE_MODE_STORAGE_KEY, isRouteStyleModeId, DEFAULT_ROUTE_STYLE_MODE_ID),
    );
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
  // 路面の2軸（路面の種類・道路の種類）は互いに独立なので常に両方同時に効かせる
  // （例:「路面の種類=アスファルトのみ」かつ「道路の種類=自転車・歩行者道のみ」を
  // 同時に絞り込みたい、という使い方に対応するため）。両軸分の非表示キーをまとめて
  // MapView/MapOverlayControlsへ渡す。
  // useMemoで参照を安定させる: このオブジェクトはMapView側のエフェクト依存
  // （applyRoadLayerState→map.setFilter）に入るため、毎レンダー新規生成すると
  // 天候取得等の無関係な再レンダーのたびにフィルタ式の再適用が走ってしまう
  // （NO_HIDDEN_LEGEND_KEYSで参照固定した意図がここで無効化されていた。設計レビューB3）。
  const roadHiddenKeysByMode = useMemo(
    () =>
      Object.fromEntries(
        ROAD_FILTER_AXES.map((axis) => [axis.id, hiddenLegendKeysByMode[axis.id] ?? NO_HIDDEN_LEGEND_KEYS]),
      ) as unknown as Record<RoadFilterAxisId, readonly string[]>,
    [hiddenLegendKeysByMode],
  );
  const hiddenRouteLegendKeys = hiddenLegendKeysByMode[routeStyleModeId] ?? NO_HIDDEN_LEGEND_KEYS;
  const toggleHiddenLegendKey = useCallback((modeId: string, key: string) => {
    setHiddenLegendKeysByMode((prev) => {
      const current = prev[modeId] ?? [];
      const next = current.includes(key) ? current.filter((k) => k !== key) : [...current, key];
      return { ...prev, [modeId]: next };
    });
  }, []);
  // 路面の絞り込み設定は別ウィンドウ（RoadFilterDialog）内でまとめて編集し、「保存」を
  // 押すまでは地図に反映しない（キャンセル/×で閉じれば破棄）。保存時にこのハンドラが
  // 一括で呼ばれ、両軸分の絞り込みキーの反映・レイヤー表示ONを1つの操作として行う。
  const handleRoadSettingsSave = useCallback((hiddenKeysByMode: Record<RoadFilterAxisId, string[]>) => {
    setHiddenLegendKeysByMode((prev) => ({ ...prev, ...hiddenKeysByMode }));
    setShowRoad(true);
  }, []);
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
          {/* 矢印記号は開閉の意味が伝わりにくかったため、より広く認知されている
              ハンバーガー/クローズアイコンに変更 */}
          {sidebarCollapsed ? "☰" : "✕"}
        </button>

        {!sidebarCollapsed && (
          <>
            <header>
              <h1 className={styles.title}>RideCompass</h1>
              <p className={styles.subtitle}>ロードバイク向け周回ルート生成アプリ（プロトタイプ）</p>
            </header>

            {/* 天候・位置情報はユーザーがまず知りたい情報のため、開発者向けの補助情報
                （デバッグモード・バックエンド疎通確認）より上に置く */}
            <div className={styles.infoCard}>
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
            </div>

            {/* 地図に何が描かれているか（色・太さの意味、絞り込み状態、ルートの色分け選択）は
                すべてここにまとめる。地図の上（MapOverlayControls）には、押下状態と
                絞り込み中を示す小さなドットだけを残し、詳細説明は地図に重ねない
                （地図の視界を優先するため）。 */}
            <div className={styles.legendCard}>
              <MapLegendPanel
                showRoad={showRoad}
                roadHiddenKeysByMode={roadHiddenKeysByMode}
                regionZoomTooWide={regionZoomTooWide}
                routeLayerOn={routeLayerOn}
                onRouteLayerToggle={setRouteLayerOn}
                routeStyleModeId={routeStyleModeId}
                onRouteStyleModeChange={handleRouteStyleModeChange}
                hiddenRouteLegendKeys={hiddenRouteLegendKeys}
                onRouteLegendToggle={handleRouteLegendToggle}
                hasDetail={hasDetail}
              />
            </div>

            <div className={styles.systemRow}>
              <DebugPanel />
              <BackendStatus />
            </div>

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
          roadHiddenKeysByMode={roadHiddenKeysByMode}
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
          roadHiddenKeysByMode={roadHiddenKeysByMode}
          onRoadSettingsSave={handleRoadSettingsSave}
          routeLayerOn={routeLayerOn}
          onRouteLayerToggle={setRouteLayerOn}
          hasDetail={hasDetail}
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
