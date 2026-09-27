"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs/Tabs";
import Disclosure from "@/components/Disclosure/Disclosure";
import { Button } from "@/components/ui/Button/Button";
import { cn } from "@/lib/cn";
import MapView from "@/features/map/MapView/MapView";
import { mapOverlayEdge, type RouteFitObscuredPx } from "@/lib/mapOverlayEdges";
import MapOverlayControls from "@/features/map/MapOverlayControls/MapOverlayControls";
import {
  ClearAllFiltersIcon,
  ClearAllLayersIcon,
  ClearRoutesIcon,
  GenerateRoutesIcon,
  RedrawMapIcon,
  RouteIcon,
  RouteSettingsIcon,
} from "@/components/ui/icons/icons";
import BottomSheet, { clampSheetHeightVh, DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import LensControl from "@/features/map/LensControl/LensControl";
import RouteForm, { type SettingsTab } from "@/features/route/RouteForm/RouteForm";
import RouteSettingsPanel from "@/features/route/RouteSettingsPanel/RouteSettingsPanel";
import HardFilterPanel from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import { useSpliceSession } from "@/features/route/useSpliceSession";
import { useGenerationConditions } from "@/features/route/useGenerationConditions";
import { useRouteGeneration } from "@/features/route/useRouteGeneration";
import { useRouteResults } from "@/features/route/useRouteResults";
import RouteOutcome from "@/features/route/RouteOutcome/RouteOutcome";
import WeatherPanel from "@/features/conditions/WeatherPanel/WeatherPanel";
import TodayOutlook from "@/features/conditions/TodayOutlook/TodayOutlook";
import WarningBadgeList, { type WarningFetchFailure } from "@/features/conditions/WarningBadge/WarningBadge";
import HeaderMenu from "@/components/HeaderMenu/HeaderMenu";
import RideConditionBar from "@/features/conditions/RideConditionBar/RideConditionBar";
import TravelBearingControl from "@/features/conditions/TravelBearingControl/TravelBearingControl";
import { useWeatherConditions } from "@/features/conditions/useWeatherConditions";
import { retryAxisCatalogFetch, useAxisCatalog } from "@/hooks/useAxisCatalog";
import DebugConsole from "@/components/DebugConsole/DebugConsole";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useElementHeightCssVar } from "@/hooks/useElementHeightCssVar";
import { useLocation } from "@/hooks/useLocation";
import { useStoredState, useStoredBooleanState } from "@/hooks/useStoredState";
import { useRideConditions } from "@/features/conditions/useRideConditions";
import { useMapView } from "@/features/map/view/useMapView";
import { textVariants } from "@/components/ui/Text/Text";
import { cardVariants } from "@/components/ui/Card/Card";
import { dotVariants } from "@/components/ui/Dot/Dot";

const GENERATE_OPEN_STORAGE_KEY = "ridecompass:generate-open";
const OUTCOME_OPEN_STORAGE_KEY = "ridecompass:outcome-open";
// モバイルの下部シートの高さ。シートは1つずつしか開かないため、1つの値を共有する。
const MOBILE_SHEET_HEIGHT_STORAGE_KEY = "ridecompass:mobile-sheet-height-vh";
// 区分の見出しのDOM id（デスクトップの区分・モバイルのシート）。
const GENERATE_SECTION_TITLE_ID = "generate-section-title";
const OUTCOME_SECTION_TITLE_ID = "outcome-section-title";
const ROUTE_SETTINGS_SHEET_TITLE_ID = "route-settings-sheet-title";
const ROUTE_OUTCOME_SHEET_TITLE_ID = "route-outcome-sheet-title";

type MobileSheet = "routeSettings" | "routeOutcome" | null;

/** 「ルート結果」をまだ開いていない新着（モバイルのタブの印）。失敗だけは色を変えて見分けられるようにする。 */
type UnseenOutcome = "failed" | "fresh";

/** モバイルの下部タブ（シートと同じ並び）。 */
const MOBILE_TABS = [
  { sheet: "routeSettings", label: "ルート設定", Icon: RouteSettingsIcon },
  { sheet: "routeOutcome", label: "ルート結果", Icon: RouteIcon },
] as const;

export default function Home() {
  const { location, locationSource, locationReady, locating, locateError, handleLocateMe, setManualLocation } =
    useLocation();

  const axisCatalog = useAxisCatalog();

  // 「ルート結果」の状態（候補・選択・押した区間・比較タブ・生成に使われた重み）。
  const results = useRouteResults();
  // 生成の結果が出て、まだ「ルート結果」を開いていない（モバイルのタブの合図）。
  const [unseenOutcome, setUnseenOutcome] = useState<UnseenOutcome | null>(null);

  // 生成の条件（「ルート設定」の入力）と走行条件。
  const conditions = useGenerationConditions({ onOriginPlace: setManualLocation });
  const ride = useRideConditions();

  // デスクトップの区分の開閉（モバイルはシートの開閉がこれに当たる）。
  const [generateOpen, setGenerateOpen] = useStoredBooleanState(GENERATE_OPEN_STORAGE_KEY, true);
  const [outcomeOpen, setOutcomeOpen] = useStoredBooleanState(OUTCOME_OPEN_STORAGE_KEY, true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  // モバイルで開いている下部シート（1つだけ。無ければ地図だけ）。
  const [mobileSheet, setMobileSheet] = useState<MobileSheet>(null);
  // シートの高さは、利用者がドラッグで確定した値だけを保存する。保存値があることが「決めた」印で、決めた後は
  // 中身に合わせた自動調整をやめる。ドラッグ中と自動調整の値は保存しない（毎フレーム書き込まない）。
  const [chosenSheetHeightVh, setChosenSheetHeightVh] = useStoredState<number | null>(
    MOBILE_SHEET_HEIGHT_STORAGE_KEY,
    null,
    {
      serialize: (v) => JSON.stringify(v),
      deserialize: (raw) => {
        try {
          const parsed = JSON.parse(raw);
          return typeof parsed === "number" && Number.isFinite(parsed) ? clampSheetHeightVh(parsed) : null;
        } catch {
          return null;
        }
      },
    },
  );
  const [workingSheetHeightVh, setWorkingSheetHeightVh] = useState<number | null>(null);
  const mobileSheetHeightVh = workingSheetHeightVh ?? chosenSheetHeightVh ?? DEFAULT_SHEET_HEIGHT_VH;
  const sheetHeightChosen = chosenSheetHeightVh !== null;

  const debugEnabled = useDebugEnabled();
  const [debugConsoleOpen, setDebugConsoleOpen] = useState(false);
  const researchEnabled = useResearchEnabled();

  const mapView = useMapView({
    hasSelectedRoute: results.selectedCandidate !== null,
    hasDetail: results.hasDetail,
    ride: ride.ride,
    now: ride.departure.now,
    usedWeights: results.usedWeights,
    currentWeights: conditions.routePreference,
  });

  // 生成の結果（候補も失敗も）は「ルート結果」でしか見えないので知らせる。デスクトップは区分を開き、モバイルは
  // タブのドットで知らせる（シートは勝手に開かない）。
  const notifyRouteOutcome = useCallback(
    (outcome: UnseenOutcome) => {
      setOutcomeOpen(true);
      setUnseenOutcome(outcome);
    },
    [setOutcomeOpen],
  );

  const generation = useRouteGeneration({
    conditions,
    origin: location,
    originKnown: locationSource !== "default",
    departure: ride.departure,
    assumedSpeedKmh: ride.speedKmh,
    lens: mapView.lens,
    hasRoutes: results.routes.length > 0,
    onGenerated: ({ routes: generated, routePreference }) => {
      results.replaceWithGenerated(generated, routePreference);
      setUnseenOutcome(generated.length > 0 ? "fresh" : null);
    },
    onOutcome: notifyRouteOutcome,
  });

  // 生成したルート（候補・選択）だけを消す。地点のピンは消さない。実験スロットも地図へ重ね描きされるので一緒に消す
  // （押した見た目どおり地図が空になる）。
  const clearResults = results.clear;
  const clearGeneration = generation.clear;
  const handleRoutesClear = useCallback(() => {
    clearResults();
    clearGeneration();
  }, [clearResults, clearGeneration]);

  // 区間の乗り換え。あれば「ルート結果」の同じ場所が編集面になる。
  const splice = useSpliceSession({
    routes: results.routes,
    generatedInput: generation.generatedInput,
    hasSelectedRoute: results.selectedCandidate !== null,
    // 作ると、直前の生成の失敗の文言を残さない。
    onApplyStart: generation.clearNotice,
    onApplied: ({ routes: nextRoutes, selectedRouteId: nextSelectedRouteId }) => {
      results.replaceAndSelect(nextRoutes, nextSelectedRouteId);
      notifyRouteOutcome("fresh");
    },
  });
  const editingRoute = splice.editingRoute;

  const isMobile = useIsMobile();

  // 「ルート設定」のタブ。タブ列は見出し行、中身は本文に描くため、両方を囲むここで持つ。
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("generate");

  // 地図でできることは、いま見ているパネルが持つ操作だけにする（地図を触った副作用で地点が変わらない）。
  // 「ルート設定」の条件タブ＝地点を置く・動かす・消す、「ルート結果」＝区間の詳細、
  // 編集中＝乗り換え先の選択だけ。モバイルはシート、デスクトップはパネルを畳んでおらず区分が開いていることが
  // 「見ているか」に当たる（畳むと区分の開閉は保ったまま中身が見えなくなる）。
  const routeSettingsActive = isMobile ? mobileSheet === "routeSettings" : !sidebarCollapsed && generateOpen;
  const routeOutcomeActive = isMobile ? mobileSheet === "routeOutcome" : !sidebarCollapsed && outcomeOpen;
  const pointEditingEnabled = routeSettingsActive && settingsTab === "generate" && editingRoute === null;
  const routeInspectionEnabled = routeOutcomeActive && editingRoute === null;
  const pinPlacementArmedRole =
    conditions.routeMode === "destination" && pointEditingEnabled ? conditions.armedPinRole : null;

  // 地図のチップ列は、下部の行（時刻スライダー等）の高さを知らない。地図の枠へ実測の高さをCSS変数で渡す。
  const mapPaneRef = useRef<HTMLDivElement>(null);
  const bottomControlRowRef = useRef<HTMLDivElement>(null);
  useElementHeightCssVar(bottomControlRowRef, mapPaneRef, "--bottom-control-row-height");

  // 地図はモバイルの下部タブバー・シートの下にも描かれるため、ルートを収めるときに覆われた高さを測って渡す
  // （そのままだとシートの裏へ収まって1本も見えない）。
  const mobileTabBarRef = useRef<HTMLElement>(null);
  const measureRouteFitObscuredPx = (): RouteFitObscuredPx | undefined => {
    if (!isMobile) return undefined;
    const sheetPx = mobileSheet ? (window.innerHeight * mobileSheetHeightVh) / 100 : 0;
    return { bottom: (mobileTabBarRef.current?.getBoundingClientRect().height ?? 0) + sheetPx };
  };

  // モバイルのタブ。同じタブをもう一度押したら閉じる。
  const handleMobileTabClick = useCallback(
    (sheet: Exclude<MobileSheet, null>) => {
      setMobileSheet((prev) => (prev === sheet ? null : sheet));
      // 「ルート結果」タブを開いたら、新着結果の合図は役目を終える。
      if (sheet === "routeOutcome") setUnseenOutcome(null);
    },
    [setMobileSheet],
  );

  const handleMobileSheetHeightCommit = useCallback(
    (vh: number) => {
      setChosenSheetHeightVh(vh);
      setWorkingSheetHeightVh(null);
    },
    [setChosenSheetHeightVh, setWorkingSheetHeightVh],
  );

  // 「今日」のパネル・最寄りの実測・警報の類（位置が決まってから、位置が変わるたびに取る。仮の地点では取らない）。
  const locationUnknown = locationReady && locationSource === "default";
  const {
    weather,
    weatherLoading,
    weatherError,
    amedas,
    amedasLoading,
    amedasError,
    warningBadgeItems,
    warningFetchFailures,
  } = useWeatherConditions(location, locationReady && !locationUnknown);
  // 取れていない前提のデータは、警報の取得失敗と同じ常設ヘッダーの印で知らせる。軸一覧が無いと、地図は道路・スポット・
  // 事故を描けず、生成は重みを送れず、合成は区間を割れない——どれも画面の中では「無い」ように見えるだけになる。
  const headerFetchFailures = useMemo<WarningFetchFailure[]>(
    () => [
      ...(locationUnknown
        ? [
            {
              id: "location",
              label: "現在地",
              effect:
                "現在地が分からないため、天候・警報を出していません。位置情報を許可するか、地図で出発地を選んでください。",
              onRetry: handleLocateMe,
            },
          ]
        : []),
      ...warningFetchFailures,
      ...(axisCatalog.failed
        ? [
            {
              id: "axis-catalog",
              label: "軸一覧",
              effect:
                "地図の道路・スポット・事故を表示できません。ルートは重み配分を変えていても反映できず、既定の配分で作ります。ルートの合成も使えません。",
              onRetry: retryAxisCatalogFetch,
            },
          ]
        : []),
    ],
    [locationUnknown, handleLocateMe, axisCatalog.failed, warningFetchFailures],
  );

  // モバイルの「ルート結果」タブの印。失敗だけ色を変える（条件の変更と新しい結果は、開けば新しいものがある点で同じ）。
  const outcomeTabSignal: { tone: "error" | "warning"; label: string } | null =
    unseenOutcome === "failed"
      ? { tone: "error", label: "生成に失敗しました" }
      : unseenOutcome === "fresh"
        ? { tone: "warning", label: "新しい結果があります" }
        : generation.conditionsDirty
          ? { tone: "warning", label: "生成条件が変更されています" }
          : null;

  // 「ルート設定」のタブ列は見出し行に置き（本文の縦を空ける）、「ルート生成」は同じ行の右端に離して置く（どのタブを
  // 見ていても押せる）。
  function renderSettingsTabs() {
    return (
      <TabsList className="gap-2 overflow-visible border-b-0" aria-label="ルート設定">
        <TabsTrigger value="generate">条件</TabsTrigger>
        <TabsTrigger value="weights">重み</TabsTrigger>
        <TabsTrigger value="exclusions">除外</TabsTrigger>
      </TabsList>
    );
  }

  function renderRouteSectionHeaderActions() {
    return (
      <div className="flex items-center gap-2">
        {/* 条件を変えている本人は設定の側を見ているので、押すべきボタンの隣でも知らせる。 */}
        {generation.conditionsDirty && (
          <span
            className={dotVariants({ tone: "warning" })}
            role="img"
            aria-label="生成条件が変更されています"
            title="生成条件が変更されています"
          />
        )}
        <Button
          variant="primary"
          size="iconLabel"
          disabled={generation.running}
          onClick={generation.submit}
          aria-label={generation.running ? (generation.progressLabel ?? "生成中...") : "ルート生成"}
        >
          <GenerateRoutesIcon size={18} />
          {generation.running ? (generation.queued ? "順番待ち" : "生成中") : "生成"}
        </Button>
      </div>
    );
  }

  // 「ルート設定」の中身（デスクトップの区分・モバイルのシートの両方）。生成の結果・誤りはここに出さない（ボタンは
  // 本文を畳んだままでも押せるため）。出し先は「ルート結果」に1つにする。
  function renderRouteSectionBody() {
    return (
      <RouteForm
        distance={conditions.distanceInput}
        onDistanceChange={conditions.setDistanceInput}
        maxRoutes={conditions.maxRoutesInput}
        onMaxRoutesChange={conditions.setMaxRoutesInput}
        routeMode={conditions.routeMode}
        onRouteModeChange={conditions.changeRouteMode}
        waypointCount={conditions.waypoints.length}
        onWaypointsClear={conditions.clearWaypoints}
        destinationSet={conditions.destination !== null}
        onDestinationClear={conditions.clearDestination}
        originManual={locationSource === "manual"}
        originLocated={locationSource !== "default"}
        onOriginReset={handleLocateMe}
        armedPinRole={conditions.armedPinRole}
        onArmPinRole={conditions.armPinRole}
        weightsPanel={
          <RouteSettingsPanel
            routePreference={conditions.routePreference}
            onRoutePreferenceChange={conditions.setRoutePreference}
            overrideEnabled={conditions.weightOverrideEnabled}
            onOverrideEnabledChange={conditions.setWeightOverrideEnabled}
          />
        }
        exclusionsPanel={
          <HardFilterPanel hardFilters={conditions.hardFilters} onHardFiltersChange={conditions.setHardFilters} />
        }
      />
    );
  }

  // 「ルート結果」の見出しの操作。候補すべてに効く操作だけを置き、候補1本への操作はその候補のタブの中に置く
  // （見出しに並べると、どれが選んでいる1本だけに効くのか見分けられない）。候補がある間だけ呼ばれる。
  function renderRouteResultHeaderActions() {
    return (
      <Button size="iconLabel" onClick={handleRoutesClear} aria-label="候補を全消去" title="候補をすべて消す">
        <ClearRoutesIcon size={18} />
        全消去
      </Button>
    );
  }

  return (
    <div className="flex h-dvh flex-col">
      <header
        className="flex flex-shrink-0 flex-nowrap items-center gap-2 overflow-x-auto border-b border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        title="風向・風速はルート候補の評価に使われます"
      >
        {/* 風と「今日」のパネルは左端に固定して常に見せる。入り切らないときに隠れるのは警報の側。 */}
        <div className="left-0 flex flex-shrink-0 items-center gap-2 sticky z-1 bg-[var(--color-surface)]">
          <WeatherPanel amedas={amedas} loading={amedasLoading} error={amedasError} />
          <TodayOutlook weather={weather} loading={weatherLoading} error={weatherError} />
        </div>
        <div className="ml-auto flex flex-shrink-0 items-center gap-2">
          <WarningBadgeList items={warningBadgeItems} failures={headerFetchFailures} />
          <div className="right-0 flex items-center sticky z-1 bg-[var(--color-surface)]">
            <HeaderMenu
              debugEnabled={debugEnabled}
              debugConsoleOpen={debugConsoleOpen}
              onToggleDebugConsole={() => setDebugConsoleOpen((v) => !v)}
            />
          </div>
        </div>
      </header>
      <DebugConsole open={debugConsoleOpen} onClose={() => setDebugConsoleOpen(false)} />

      <div className="app-shell">
        {!isMobile && (
          <aside className={`app-sidebar${sidebarCollapsed ? " is-collapsed" : ""}`}>
            <Button
              size="sm"
              onClick={() => setSidebarCollapsed((v) => !v)}
              aria-label={sidebarCollapsed ? "パネルを開く" : "パネルを閉じる"}
              className="self-start"
            >
              {sidebarCollapsed ? "☰" : "✕"}
            </Button>

            {!sidebarCollapsed && (
              <>
                {/* モバイルの下部タブと同じ区分・同じ順序。タブ列（見出し行）とタブの中身（本文）の両方を囲む。 */}
                <Tabs value={settingsTab} onValueChange={(value) => setSettingsTab(value as SettingsTab)}>
                  <Disclosure
                    className="border-t border-[var(--color-border)] pt-2"
                    headerClassName={"flex items-center justify-between gap-2"}
                    triggerClassName={cn(
                      textVariants({ variant: "heading" }),
                      "group flex cursor-pointer items-center gap-1.5",
                    )}
                    bodyClassName={"flex flex-col gap-2"}
                    id={GENERATE_SECTION_TITLE_ID}
                    summary={
                      <>
                        <span
                          aria-hidden="true"
                          className="size-2 flex-shrink-0 -rotate-45 border-r-2 border-b-2 border-[var(--color-neutral)] transition-transform duration-150 group-data-[state=open]:rotate-45"
                        />
                        ルート設定
                      </>
                    }
                    trailing={
                      <div className="flex min-w-0 flex-auto items-center justify-between gap-2">
                        {renderSettingsTabs()}
                        {renderRouteSectionHeaderActions()}
                      </div>
                    }
                    open={generateOpen}
                    onOpenChange={setGenerateOpen}
                  >
                    {renderRouteSectionBody()}
                  </Disclosure>
                </Tabs>

                <Disclosure
                  className="border-t border-[var(--color-border)] pt-2"
                  headerClassName={"flex items-center justify-between gap-2"}
                  triggerClassName={cn(
                    textVariants({ variant: "heading" }),
                    "group flex cursor-pointer items-center gap-1.5",
                  )}
                  bodyClassName={"flex flex-col gap-2"}
                  id={OUTCOME_SECTION_TITLE_ID}
                  summary={
                    <>
                      <span
                        aria-hidden="true"
                        className="size-2 flex-shrink-0 -rotate-45 border-r-2 border-b-2 border-[var(--color-neutral)] transition-transform duration-150 group-data-[state=open]:rotate-45"
                      />
                      ルート結果
                    </>
                  }
                  trailing={
                    results.routes.length > 0 ? (
                      <div className="flex flex-shrink-0 items-center gap-2">{renderRouteResultHeaderActions()}</div>
                    ) : undefined
                  }
                  open={outcomeOpen}
                  onOpenChange={setOutcomeOpen}
                >
                  <RouteOutcome
                    results={results}
                    generation={generation}
                    splice={splice}
                    currentWeights={conditions.routePreference}
                  />
                </Disclosure>
              </>
            )}
          </aside>
        )}

        {/* 下部シートの高さを地図の側へ渡す（地図の操作ボタンは画面の下端からの距離で置くため、シートの裏へ隠れない
            よう持ち上げる）。 */}
        <div
          ref={mapPaneRef}
          className="app-map-pane relative flex-1"
          style={
            {
              "--mobile-sheet-height": isMobile && mobileSheet ? `${mobileSheetHeightVh}vh` : "0px",
            } as React.CSSProperties
          }
        >
          <MapView
            routes={results.routes}
            {...splice.map}
            selectedRouteId={results.selectedRouteId}
            location={location}
            locationSource={locationSource}
            look={mapView.look}
            rideConditions={ride.ride}
            routePreference={conditions.routePreferenceToSend}
            // 実験スロットは「比較」を見ている間だけ地図へ重ねる（それ以外は選んだルートの色分けと紛らわしい）。
            experimentSlots={researchEnabled && results.comparisonTabActive ? generation.experimentSlots : []}
            selectedRouteSegment={results.selectedRouteSegment}
            onRouteSegmentSelect={(selection) => {
              if (!routeInspectionEnabled) return;
              results.selectSegment(selection);
            }}
            waypoints={conditions.routeMode === "destination" ? conditions.waypoints : []}
            onWaypointRemove={conditions.removeWaypoint}
            onWaypointMove={conditions.moveWaypoint}
            destination={conditions.routeMode === "destination" ? conditions.destination : null}
            onDestinationClear={conditions.clearDestination}
            armedPinRole={pinPlacementArmedRole}
            pointEditingEnabled={pointEditingEnabled}
            onPinPlace={conditions.placePin}
            measureRouteFitObscuredPx={measureRouteFitObscuredPx}
          />

          <LensControl {...mapView.lensControl} />

          <MapOverlayControls {...mapView.overlayControls} />

          {/* 地図の下の中央に「まとめて元に戻す」操作を並べる（レイヤーのON/OFFと凡例の絞り込みは別の状態）。 */}
          <div
            ref={bottomControlRowRef}
            {...mapOverlayEdge("bottom")}
            className="pointer-events-none absolute bottom-3 left-1/2 z-[var(--z-map-control)] flex max-w-[100vw] -translate-x-1/2 flex-row items-center gap-2 max-mobile:bottom-[max(calc(var(--space-3)+var(--mobile-tabbar-height)),calc(var(--space-2)+var(--mobile-tabbar-height)+var(--mobile-sheet-height)))]"
          >
            <Button
              variant="float"
              size="iconRound"
              onClick={mapView.bulk.hideAllLayers}
              disabled={!mapView.bulk.anyLayerOn}
              aria-label="表示中のレイヤーをすべて非表示にする"
              title="表示中のレイヤーをすべて非表示にする"
            >
              <ClearAllLayersIcon size={14} />
            </Button>
            <Button
              variant="float"
              size="iconRound"
              onClick={mapView.bulk.showAllLegendRows}
              disabled={!mapView.bulk.anyLegendHidden}
              aria-label="絞り込みをすべて解除する"
              title="絞り込みをすべて解除する"
            >
              <ClearAllFiltersIcon size={14} />
            </Button>
            {/* 押した人の地図だけを描き直す（ページを読み込み直すと生成したルートが消える）。 */}
            <Button
              variant="float"
              size="iconRound"
              onClick={mapView.bulk.redraw}
              aria-label="地図の表示を再描画する"
              title="地図の表示を再描画する"
            >
              <RedrawMapIcon size={14} />
            </Button>
          </div>

          <TravelBearingControl value={ride.bearingDeg} onChange={ride.setBearingDeg} />

          {/* 走行条件（出発時刻・想定速度）は走行方位の直下に積む。出発時刻は気象レイヤーの表示時刻と同じもの。 */}
          <div
            {...mapOverlayEdge("right")}
            className="pointer-events-none absolute top-[calc(var(--map-ctrl-stack-top)+var(--map-ctrl-button-size)+var(--map-ctrl-stack-gap))] right-[var(--map-ctrl-margin)] z-[var(--z-map-control)]"
          >
            <RideConditionBar
              departureTime={ride.departure.at}
              onDepartureTimeChange={ride.departure.setAt}
              onDepartureNow={ride.departure.followNow}
              speedKmh={ride.speedKmh}
              onSpeedKmhChange={ride.setSpeedKmh}
            />
          </div>

          <Button
            variant="float"
            size="bare"
            shape="pill"
            onClick={handleLocateMe}
            disabled={locating}
            {...mapOverlayEdge("right")}
            aria-label="現在地に移動"
            title="現在地に移動"
            className={cn(
              "absolute right-[calc(var(--map-ctrl-margin)+(var(--map-ctrl-column-width)-44px)/2)] bottom-10 z-[var(--z-map-control)] max-mobile:bottom-[max(calc(5rem+var(--mobile-tabbar-height)),calc(var(--space-2)+var(--mobile-tabbar-height)+var(--mobile-sheet-height)))]",
              "size-11 text-[1.3rem]",
              locating && "cursor-wait opacity-60",
            )}
          >
            {locating ? (
              "…"
            ) : (
              // 文字の「◎」は書体によって中央の点が描かれないため、SVGで描く。
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
          </Button>

          {locateError && (
            <p
              className={cn(
                cardVariants({ variant: "float" }),
                "pointer-events-none absolute right-3 bottom-25 z-[var(--z-map-control)] max-w-55 border-0 px-2.5 py-1.5 text-[length:var(--font-size-sm)] text-[var(--color-danger)] max-mobile:bottom-[max(calc(8.5rem+var(--mobile-tabbar-height)),calc(var(--space-2)+3.5rem+var(--mobile-tabbar-height)+var(--mobile-sheet-height)))]",
              )}
            >
              {locateError}
            </p>
          )}
        </div>
      </div>

      {/* モバイル: 下部タブと部分シート。シートを開いたままでも地図の上側は見えて動かせる。 */}
      {isMobile && (
        <>
          <nav
            ref={mobileTabBarRef}
            className="fixed right-0 bottom-0 left-0 z-[var(--z-bottom-sheet)] flex h-[var(--mobile-tabbar-height)] touch-none border-t border-[var(--color-border)] bg-[var(--color-surface)] shadow-[0_-1px_8px_rgba(0,0,0,0.15)]"
            aria-label="パネル切り替え"
          >
            {MOBILE_TABS.map(({ sheet, label, Icon }) => (
              <Button
                key={sheet}
                variant="ghost"
                size="bare"
                className="relative min-h-11 flex-1 touch-none flex-col gap-0.5 rounded-none border-0 text-[var(--foreground)] aria-expanded:bg-[var(--color-accent-bg)] aria-expanded:font-bold aria-expanded:text-[var(--color-accent-strong)]"
                aria-expanded={mobileSheet === sheet}
                aria-description={sheet === "routeOutcome" ? outcomeTabSignal?.label : undefined}
                onClick={() => handleMobileTabClick(sheet)}
              >
                <Icon />
                <span className="text-[0.62rem] leading-none whitespace-nowrap">{label}</span>
                {sheet === "routeOutcome" && outcomeTabSignal && (
                  <span
                    aria-hidden="true"
                    className={cn(dotVariants({ tone: outcomeTabSignal.tone }), "absolute top-1.5 right-2.5")}
                  />
                )}
              </Button>
            ))}
          </nav>

          <Tabs value={settingsTab} onValueChange={(value) => setSettingsTab(value as SettingsTab)}>
            <BottomSheet
              open={mobileSheet === "routeSettings"}
              onClose={() => setMobileSheet(null)}
              title="ルート設定"
              titleId={ROUTE_SETTINGS_SHEET_TITLE_ID}
              headerLead={renderSettingsTabs()}
              headerAction={renderRouteSectionHeaderActions()}
              heightVh={mobileSheetHeightVh}
              onHeightChange={setWorkingSheetHeightVh}
              onHeightCommit={handleMobileSheetHeightCommit}
              autoFitHeight={!sheetHeightChosen}
              fitKey={`${settingsTab}:${conditions.routeMode}`}
            >
              {renderRouteSectionBody()}
            </BottomSheet>
          </Tabs>

          <BottomSheet
            open={mobileSheet === "routeOutcome"}
            onClose={() => setMobileSheet(null)}
            title="ルート結果"
            titleId={ROUTE_OUTCOME_SHEET_TITLE_ID}
            headerAction={results.routes.length > 0 ? renderRouteResultHeaderActions() : undefined}
            heightVh={mobileSheetHeightVh}
            onHeightChange={setWorkingSheetHeightVh}
            onHeightCommit={handleMobileSheetHeightCommit}
            autoFitHeight={!sheetHeightChosen}
          >
            <RouteOutcome
              results={results}
              generation={generation}
              splice={splice}
              currentWeights={conditions.routePreference}
            />
          </BottomSheet>
        </>
      )}
    </div>
  );
}
