"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapView from "@/components/Map/MapView";
import BackendStatus from "@/components/BackendStatus";
import DebugPanel from "@/components/DebugPanel/DebugPanel";
import ResearchPanel from "@/components/ResearchPanel/ResearchPanel";
import DebugConsole, { DEBUG_CONSOLE_MAX_HEIGHT_PX } from "@/components/DebugConsole/DebugConsole";
import LocationControl from "@/components/LocationControl/LocationControl";
import MapOverlayControls, { type OverlayLayerChip } from "@/components/MapOverlayControls/MapOverlayControls";
import MapLayersPanel from "@/components/MapLayersPanel/MapLayersPanel";
import {
  MAP_LAYERS,
  layerSectionDomId,
  type MapLayerId,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import { summarizeLegendFilters } from "@/components/Map/legendFilter";
import { ROAD_FILTER_AXES, type RoadFilterAxisId } from "@/components/Map/roadFilterAxes";
import { getRouteStyleMode } from "@/components/Map/routeStyleModes";
import {
  DEFAULT_ROUTE_STYLE_MODE_ID,
  isRouteStyleModeId,
  type RouteStyleModeId,
} from "@/components/Map/routeStyleModes";
import RouteForm from "@/components/RouteForm/RouteForm";
import RouteList from "@/components/RouteList/RouteList";
import WeatherPanel from "@/components/WeatherPanel/WeatherPanel";
import WeightPanel, { DEFAULT_ROUTE_PREFERENCE, DEFAULT_SCORING_WEIGHTS } from "@/components/WeightPanel/WeightPanel";
import ComparisonPanel from "@/components/ComparisonPanel/ComparisonPanel";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useIsomorphicLayoutEffect } from "@/hooks/useIsomorphicLayoutEffect";
import { useLocation } from "@/hooks/useLocation";
import { generateRoutes } from "@/services/routeApi";
import { getCurrentWeather } from "@/services/weatherApi";
import type { Coordinates, RouteCandidate, RoutePreferenceWeights, ScoringWeights } from "@/types/route";
import type { WeatherConditions } from "@/types/weather";
import { EXPERIMENT_SLOT_COLORS, MAX_EXPERIMENT_SLOTS, type ExperimentSlot } from "@/types/experimentSlot";
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

  // 評価重みのリクエスト上書き（研究インターフェース改善 §10-1/4）。overrideEnabled=falseの間は
  // 生成リクエストからscoring_weights/route_preferenceを省略し、既存挙動（YAML既定値）を
  // 完全に維持する（一般ユーザーには影響しない）。
  const [weightOverrideEnabled, setWeightOverrideEnabled] = useState(false);
  const [scoringWeights, setScoringWeights] = useState<ScoringWeights>(DEFAULT_SCORING_WEIGHTS);
  const [routePreference, setRoutePreference] = useState<RoutePreferenceWeights>(DEFAULT_ROUTE_PREFERENCE);

  // 実験スロット（研究インターフェース改善 §10-3）: デバッグモード中の生成結果を条件付きで
  // 直近MAX_EXPERIMENT_SLOTS件だけメモリ内に保持し、地図重ね描き・比較表に使う。
  const [experimentSlots, setExperimentSlots] = useState<ExperimentSlot[]>([]);
  const [weather, setWeather] = useState<WeatherConditions | null>(null);
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [weatherError, setWeatherError] = useState<string | null>(null);

  // 地図レイヤーのON/OFF（MAP_LAYERSのid単位。レイヤーを追加したらここへ初期値を1つ足す）
  const [layerVisibility, setLayerVisibility] = useState<MapLayerVisibility>({
    elevation: false,
    road: false,
    trafficStress: false,
    bicycleInfra: false,
    route: true,
  });
  const [routeStyleModeId, setRouteStyleModeId] = useState<RouteStyleModeId>(DEFAULT_ROUTE_STYLE_MODE_ID);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [regionZoomTooWide, setRegionZoomTooWide] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);

  const toggleButtonRef = useRef<HTMLButtonElement>(null);
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);
  const debugEnabled = useDebugEnabled();
  const researchEnabled = useResearchEnabled();

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
  // 路面の絞り込み設定はサイドバーのRoadFilterEditor内で下書き編集し、「適用」を押すまで
  // 地図に反映しない。適用時にこのハンドラが一括で呼ばれ、両軸分の絞り込みキーの反映・
  // レイヤー表示ONを1つの操作として行う。
  const handleRoadFilterApply = useCallback((hiddenKeysByMode: Record<RoadFilterAxisId, string[]>) => {
    setHiddenLegendKeysByMode((prev) => ({ ...prev, ...hiddenKeysByMode }));
    setLayerVisibility((prev) => ({ ...prev, road: true }));
  }, []);
  const handleRouteLegendToggle = useCallback(
    (key: string) => toggleHiddenLegendKey(routeStyleModeId, key),
    [routeStyleModeId, toggleHiddenLegendKey],
  );

  const handleLayerToggle = useCallback((id: MapLayerId, on: boolean) => {
    setLayerVisibility((prev) => ({ ...prev, [id]: on }));
  }, []);

  // 地図上（MapOverlayControls）のサマリ行に出す「適用中の条件」の1行要約。
  // 路面はズーム不足の案内を絞り込みより優先する（ONにしたのに何も出ない状態の説明が先）。
  const roadFilterSummary = useMemo(
    () =>
      summarizeLegendFilters(
        ROAD_FILTER_AXES.map((axis) => ({
          label: axis.label,
          legend: axis.legend,
          hiddenKeys: roadHiddenKeysByMode[axis.id] ?? NO_HIDDEN_LEGEND_KEYS,
        })),
      ),
    [roadHiddenKeysByMode],
  );
  const roadSummary = regionZoomTooWide ? "ズームインすると表示されます" : roadFilterSummary;
  // ルートは色分けモード自体が「何の条件で色分け中か」の情報なので常に出す
  const routeSummary = hasDetail
    ? `色分け: ${getRouteStyleMode(routeStyleModeId).label}${hiddenRouteLegendKeys.length > 0 ? "・一部非表示" : ""}`
    : null;

  // 地図上のチップ行はレイヤーカタログ（MAP_LAYERS）から組み立てる。レイヤーを追加したら
  // summaryの対応をここへ1行足すだけでよい（チップ・サマリ行の描画は汎用）。
  const overlayLayers = useMemo<OverlayLayerChip[]>(
    () =>
      MAP_LAYERS.map((layer) => {
        const disabled = layer.id === "route" && !hasDetail;
        const summary = layer.id === "road" ? roadSummary : layer.id === "route" ? routeSummary : null;
        return {
          id: layer.id,
          label: layer.label,
          on: layerVisibility[layer.id],
          disabled,
          title: disabled ? "ルートを生成・選択すると使えます" : `${layer.description}（設定はサイドバー）`,
          summary,
        };
      }),
    [hasDetail, layerVisibility, roadSummary, routeSummary],
  );

  // 地図上の条件サマリのタップで、サイドバーを開いて該当レイヤーの設定セクションへ誘導する。
  // サイドバーが閉じていると中身が未マウントのため、開いた後の再レンダーを待ってから
  // （次フレームで）スクロール・フォーカスする。
  const handleLayerSummaryClick = useCallback((id: MapLayerId) => {
    setSidebarCollapsed(false);
    requestAnimationFrame(() => {
      const heading = document.getElementById(`${layerSectionDomId(id)}-title`);
      heading?.scrollIntoView?.({ block: "start", behavior: "smooth" });
      heading?.focus?.({ preventScroll: true });
    });
  }, []);

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
      const { routes: candidates, conditions, engine } = await generateRoutes({
        latitude: location.latitude,
        longitude: location.longitude,
        distance_km: distanceKm,
        distance_tolerance_km: DISTANCE_TOLERANCE_KM,
        route_type: "loop",
        ...(weightOverrideEnabled ? { scoring_weights: scoringWeights, route_preference: routePreference } : {}),
      });
      setRoutes(candidates);
      setSelectedRouteId(candidates[0]?.id ?? null);
      if (candidates.length === 0) {
        setErrorMessage("条件に合うルート候補が見つかりませんでした。距離を変えて試してください。");
      } else if (researchEnabled) {
        // 実験スロットへの記録は研究モード中の生成のみ（研究用機能を一般ユーザーの
        // 通常操作から隠す方針、§14。ログ表示のデバッグモードとは独立、改善計画T29）。
        // おすすめ度最上位（=candidates[0]）を比較代表候補として
        // 固定し、以降の候補選び直しでは変えない（スロット=生成結果のスナップショット）。
        setExperimentSlots((prev) => {
          const next: ExperimentSlot = {
            id: `slot-${conditions.generated_at}-${Math.random().toString(36).slice(2, 8)}`,
            color: EXPERIMENT_SLOT_COLORS[0],
            conditions,
            engine,
            topCandidate: candidates[0],
          };
          // 色は「最新=0番目の色」という表示順ベースで割り当てる（スロットの入れ替わりに
          // 関わらず、常に同じ位置=同じ色になるようにするため。個々のスロットに色を固定すると
          // 古いスロットが押し出された後も残ったスロットの色がずれて見える）。
          return [next, ...prev]
            .slice(0, MAX_EXPERIMENT_SLOTS)
            .map((slot, i) => ({ ...slot, color: EXPERIMENT_SLOT_COLORS[i % EXPERIMENT_SLOT_COLORS.length] }));
        });
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

            {/* 地図レイヤーの「細かな設定」（ON/OFF・凡例・絞り込み編集・ルートの色分け選択）は
                すべてここにまとめる。地図の上（MapOverlayControls）にはON/OFFチップと
                適用中の条件の1行サマリだけを残し、詳細は地図に重ねない（地図の視界を優先）。
                サマリのタップでこのパネルの該当セクションへスクロールしてくる。 */}
            <div className={styles.legendCard}>
              <MapLayersPanel
                layerVisibility={layerVisibility}
                onLayerToggle={handleLayerToggle}
                roadHiddenKeysByMode={roadHiddenKeysByMode}
                onRoadFilterApply={handleRoadFilterApply}
                regionZoomTooWide={regionZoomTooWide}
                routeStyleModeId={routeStyleModeId}
                onRouteStyleModeChange={handleRouteStyleModeChange}
                hiddenRouteLegendKeys={hiddenRouteLegendKeys}
                onRouteLegendToggle={handleRouteLegendToggle}
                hasDetail={hasDetail}
              />
            </div>

            <div className={styles.systemRow}>
              <DebugPanel />
              <ResearchPanel />
              <BackendStatus />
            </div>

            {/* 評価重みパネルは研究インターフェース改善のPhase2（§10-1/4）。研究モード配下に
                置き、一般ユーザーの操作導線とは混ざらない場所にする（§14の分離方針）。 */}
            {researchEnabled && (
              <div className={styles.legendCard}>
                <WeightPanel
                  overrideEnabled={weightOverrideEnabled}
                  onOverrideEnabledChange={setWeightOverrideEnabled}
                  scoringWeights={scoringWeights}
                  onScoringWeightsChange={setScoringWeights}
                  routePreference={routePreference}
                  onRoutePreferenceChange={setRoutePreference}
                />
              </div>
            )}

            {/* ルート生成は「地図レイヤーだけ使いたい」用途では不要なため、折りたたみ
                （デフォルト閉）にして地図側の視界を優先する。候補一覧・エラーもルート生成の
                一部としてこの中にまとめる（レイヤーのON/OFFは地図上のMapOverlayControlsへ移動済み）。 */}
            <details className={styles.routeSection}>
              <summary className={styles.routeSectionSummary}>ルート生成</summary>
              <RouteForm onGenerate={handleGenerate} loading={loading} />
              {errorMessage && <p className={styles.errorMessage}>{errorMessage}</p>}
              <RouteList routes={routes} selectedRouteId={selectedRouteId} onSelect={setSelectedRouteId} />
              {/* 実験スロット比較表（研究インターフェース改善 §10-3）。デバッグモード中の生成が
                  2件以上たまったときだけ表示する。 */}
              <ComparisonPanel slots={experimentSlots} />
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
          showElevation={layerVisibility.elevation}
          showRoad={layerVisibility.road}
          showTrafficStress={layerVisibility.trafficStress}
          showBicycleInfra={layerVisibility.bicycleInfra}
          roadHiddenKeysByMode={roadHiddenKeysByMode}
          routeLayerOn={layerVisibility.route}
          routeStyleModeId={routeStyleModeId}
          hiddenRouteLegendKeys={hiddenRouteLegendKeys}
          onRegionZoomHintChange={setRegionZoomTooWide}
          refreshToken={refreshToken}
          experimentSlots={researchEnabled ? experimentSlots : []}
        />

        <MapOverlayControls layers={overlayLayers} onToggle={handleLayerToggle} onSummaryClick={handleLayerSummaryClick} />

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
