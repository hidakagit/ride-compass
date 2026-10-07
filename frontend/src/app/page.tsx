"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs/Tabs";
import Disclosure from "@/components/Disclosure/Disclosure";
import ErrorText from "@/features/route/ErrorText/ErrorText";
import { Button } from "@/components/ui/Button/Button";
import { ConfirmDialog } from "@/components/ui/Dialog/Dialog";
import { cn } from "@/lib/cn";
import MapView from "@/features/map/MapView/MapView";
import { mapOverlayEdge, type RouteFitObscuredPx } from "@/lib/mapOverlayEdges";
import MapOverlayControls from "@/features/map/MapOverlayControls/MapOverlayControls";
import {
  ClearAllFiltersIcon,
  ClearAllLayersIcon,
  ClearRoutesIcon,
  GenerateRoutesIcon,
  LocateIcon,
  RedrawMapIcon,
  RouteIcon,
  RouteSettingsIcon,
} from "@/components/ui/icons/icons";
import BottomSheet, { clampSheetHeightVh, DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import LensControl from "@/features/map/LensControl/LensControl";
import RouteForm, { type SettingsTab } from "@/features/route/RouteForm/RouteForm";
import RouteSettingsPanel from "@/features/route/RouteSettingsPanel/RouteSettingsPanel";
import HardFilterPanel from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import SavedConditionsPanel from "@/features/route/SavedConditionsPanel/SavedConditionsPanel";
import { useGenerationConditions } from "@/features/route/useGenerationConditions";
import { useSavedConditions } from "@/features/route/useSavedConditions";
import type { RouteOutcomeKind } from "@/features/route/useRouteGeneration";
import { useRoutePlanner } from "@/features/route/useRoutePlanner";
import RouteOutcome from "@/features/route/RouteOutcome/RouteOutcome";
import WeatherPanel from "@/features/conditions/WeatherPanel/WeatherPanel";
import TodayOutlook from "@/features/conditions/TodayOutlook/TodayOutlook";
import WarningBadgeList from "@/features/conditions/WarningBadge/WarningBadge";
import HeaderMenu from "@/components/HeaderMenu/HeaderMenu";
import UsageGuide from "@/components/UsageGuide/UsageGuide";
import FirstVisitIntro from "@/components/FirstVisitIntro/FirstVisitIntro";
import RideConditionBar from "@/features/conditions/RideConditionBar/RideConditionBar";
import TravelBearingControl from "@/features/conditions/TravelBearingControl/TravelBearingControl";
import { useWeatherConditions } from "@/features/conditions/useWeatherConditions";
import { axisCatalogFetchFailure, useAxisCatalog } from "@/hooks/useAxisCatalog";
import DebugConsole from "@/components/DebugConsole/DebugConsole";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useElementHeightCssVar } from "@/hooks/useElementHeightCssVar";
import { useLocation } from "@/hooks/useLocation";
import { useStoredState, useStoredBooleanState } from "@/hooks/useStoredState";
import { useRideConditions } from "@/features/conditions/useRideConditions";
import { formatDepartureLabel } from "@/features/conditions/rideConditions";
import { useMapView } from "@/features/map/view/useMapView";
import { textVariants } from "@/components/ui/Text/Text";
import { cardVariants } from "@/components/ui/Card/Card";
import { dotVariants } from "@/components/ui/Dot/Dot";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";

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

/** モバイルの下部タブの使い方。 */
const MOBILE_TAB_USAGES = {
  routeSettings:
    "ルートを作る条件[距離・地点・重み・除外・保存した設定]と「ルート生成」を開きます。もう一度押すと閉じます。",
  routeOutcome: "作った候補の一覧と、その難易度の内訳を開きます。点は新しい結果か条件の変更の合図で、赤は失敗です。",
} as const;

/** モバイルの下部タブ（シートと同じ並び）。 */
const MOBILE_TABS = [
  { sheet: "routeSettings", label: "ルート設定", Icon: RouteSettingsIcon },
  { sheet: "routeOutcome", label: "ルート結果", Icon: RouteIcon },
] as const;

export default function Home() {
  const {
    location,
    locationSource,
    locationKnown,
    locationFailure,
    locating,
    locateError,
    handleLocateMe,
    setManualLocation,
  } = useLocation();

  const axisCatalog = useAxisCatalog();

  // 生成の結果が出て、まだ「ルート結果」を開いていない（モバイルのタブの合図）。失敗だけは色を変えて見分けられるようにする。
  const [unseenOutcome, setUnseenOutcome] = useState<RouteOutcomeKind | null>(null);

  // 生成の条件（「ルート設定」の入力）と走行条件。
  const conditions = useGenerationConditions({ onOriginPlace: setManualLocation });
  const ride = useRideConditions();
  // 名前を付けて保存した生成の条件（「保存」タブ）。
  const savedConditions = useSavedConditions({
    conditions,
    origin: locationKnown ? location : null,
    originManual: locationSource === "manual",
    onOriginPlace: setManualLocation,
    onOriginFollowCurrent: handleLocateMe,
  });

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
  // 説明を見る状態（ヘッダーのメニューの「使い方を見る」で入る）。
  const [usageGuideActive, setUsageGuideActive] = useState(false);

  // 生成と乗り換えの結果（候補も失敗も）は「ルート結果」でしか中身が見えないので知らせる。デスクトップは区分を開き、
  // モバイルはタブのドットで知らせる（シートは勝手に開かない）。
  const notifyRouteOutcome = useCallback(
    (outcome: RouteOutcomeKind) => {
      setOutcomeOpen(true);
      setUnseenOutcome(outcome);
    },
    [setOutcomeOpen],
  );

  // ルートを作る機能（結果・生成・区間の乗り換え）。
  const route = useRoutePlanner({
    conditions,
    origin: location,
    originKnown: locationKnown,
    departure: ride.departure,
    assumedSpeedKmh: ride.speedKmh,
    onOutcome: notifyRouteOutcome,
  });
  const { results, generation, splice } = route;
  const editingRoute = splice.editingRoute;
  // 「候補を全消去」を押したか。確認の窓で「消す」を押すまで消さない。
  const [confirmingClear, setConfirmingClear] = useState(false);

  const mapView = useMapView({
    hasSelectedRoute: results.selectedCandidate !== null,
    hasDetail: results.hasDetail,
    ride: ride.ride,
    now: ride.departure.now,
    departureLabel: formatDepartureLabel(ride.departure.at, ride.departure.now),
    routeWeights: route.routeWeights,
  });

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
  const pinPlacementArmedRole = pointEditingEnabled ? conditions.armedPinRole : null;

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

  // 「今日」のパネル・最寄りの実測・警報の類（位置が分かってから、位置が変わるたびに取る。仮の地点では取らない）。
  const {
    weather,
    weatherLoading,
    weatherError,
    amedas,
    amedasLoading,
    amedasError,
    warningBadgeItems,
    warningFetchFailures,
  } = useWeatherConditions(location, locationKnown);
  const axisCatalogFailure = axisCatalogFetchFailure(axisCatalog);
  const headerFetchFailures = useMemo(
    () => [
      ...(locationFailure ? [locationFailure] : []),
      ...warningFetchFailures,
      ...(axisCatalogFailure ? [axisCatalogFailure] : []),
    ],
    [locationFailure, warningFetchFailures, axisCatalogFailure],
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
        <TabsTrigger value="generate" usage="周回か目的地か、距離・地点・候補の数を決めます。">
          条件
        </TabsTrigger>
        <TabsTrigger value="weights" usage="道を選ぶときに、どの評価軸をどれだけ重く見るかを決めます。">
          重み
        </TabsTrigger>
        <TabsTrigger value="exclusions" usage="ルートに使わない道路の種類を選びます。">
          除外
        </TabsTrigger>
        <TabsTrigger value="saved" usage="いまの設定に名前を付けて保存し、保存した設定を呼び出します。">
          保存
        </TabsTrigger>
      </TabsList>
    );
  }

  function renderRouteSectionHeaderActions() {
    return (
      <div className="flex items-center gap-2">
        {/* 条件を変えている本人は設定の側を見ているので、押すべきボタンの隣でも知らせる。 */}
        {generation.conditionsDirty && (
          <InfoPopover
            triggerAriaLabel="生成条件の変更"
            triggerContent={<span className={dotVariants({ tone: "warning" })} />}
          >
            生成条件が変更されています。表示中の候補は変更前の条件で作ったものです。
          </InfoPopover>
        )}
        <Button
          variant="primary"
          size="panelIcon"
          disabled={generation.running}
          onClick={() => void generation.submit(mapView.lens)}
          aria-label={generation.running ? (generation.progressLabel ?? "生成中...") : "ルート生成"}
          usage="いまの条件・重み・除外でルートの候補を作ります。候補は「ルート結果」に並び、地図に線が出ます。"
        >
          <GenerateRoutesIcon size={18} />
        </Button>
      </div>
    );
  }

  // 「ルート設定」の中身（デスクトップの区分・モバイルのシートの両方）。生成の結果・誤りはここに出さない（ボタンは
  // 本文を畳んだままでも押せるため）。出し先は「ルート結果」で、モバイルのシートだけは入力の誤りも添える（シートの側）。
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
        originLocated={locationKnown}
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
        savedPanel={
          <SavedConditionsPanel
            saved={savedConditions.saved}
            current={savedConditions.current}
            suggestedName={savedConditions.suggestedName}
            originManual={locationSource === "manual"}
            originKnown={locationKnown}
            onSave={savedConditions.save}
            onRecall={savedConditions.recall}
            onRemove={savedConditions.remove}
          />
        }
      />
    );
  }

  // 「ルート結果」の見出しの操作。候補すべてに効く操作だけを置き、候補1本への操作はその候補のタブの中に置く
  // （見出しに並べると、どれが選んでいる1本だけに効くのか見分けられない）。候補がある間だけ呼ばれる。
  function renderRouteResultHeaderActions() {
    return (
      <>
        <Button
          size="panelIcon"
          onClick={() => setConfirmingClear(true)}
          aria-label="候補を全消去"
          aria-haspopup="dialog"
          aria-expanded={confirmingClear}
          usage="作った候補をすべて消します。地図に置いた地点は残ります。"
        >
          <ClearRoutesIcon size={18} />
        </Button>
        <ConfirmDialog
          open={confirmingClear}
          title="候補をすべて消します"
          confirmLabel="消す"
          onCancel={() => setConfirmingClear(false)}
          onConfirm={() => {
            setConfirmingClear(false);
            route.clear();
          }}
        >
          消した候補は元に戻せません。地図に置いた地点は残ります。
        </ConfirmDialog>
      </>
    );
  }

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex flex-shrink-0 flex-nowrap items-center gap-2 overflow-x-auto border-b border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
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
              onStartUsageGuide={() => setUsageGuideActive(true)}
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
              usage="左のパネルを畳んで地図を広く見ます。もう一度押すと開きます。"
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
                    usage="押すと開き・畳みます。ルートを作る条件をここで決め、右の「ルート生成」で作ります。"
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
                  usage="押すと開き・畳みます。作った候補と、その難易度の内訳がここに並びます。"
                >
                  <RouteOutcome
                    results={results}
                    generation={generation}
                    splice={splice}
                    routeWeights={route.routeWeights}
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
            routes={route.mapRoutes}
            {...splice.map}
            selectedRouteId={results.selectedRouteId}
            location={location}
            locationSource={locationSource}
            look={mapView.look}
            rideConditions={ride.ride}
            routePreference={conditions.routePreferenceToSend}
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

          <FirstVisitIntro isMobile={isMobile} locationUnknown={locationFailure !== null} />

          {usageGuideActive && <UsageGuide onEnd={() => setUsageGuideActive(false)} />}

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
              usage="地図の左のチップでONにした表示を、まとめてOFFにします。"
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
              usage="凡例のチェックを外して隠した段階を、まとめて地図に戻します。"
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
              usage="地図の表示が欠けたときに、地図だけを描き直します。作ったルートは消えません。"
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
            usage="現在地を取り直して地図をそこへ動かし、出発地を現在地にします。"
            className={cn(
              "absolute right-[calc(var(--map-ctrl-margin)+(var(--map-ctrl-column-width)-44px)/2)] bottom-10 z-[var(--z-map-control)] max-mobile:bottom-[max(calc(5rem+var(--mobile-tabbar-height)),calc(var(--space-2)+var(--mobile-tabbar-height)+var(--mobile-sheet-height)))]",
              "size-11 text-[1.3rem]",
              locating && "cursor-wait opacity-60",
            )}
          >
            {locating ? "…" : <LocateIcon size={20} />}
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
                usage={MOBILE_TAB_USAGES[sheet]}
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
              {/* シートは1枚ずつしか開かず「ルート結果」の誤りは見えないため、直す場所であるここにも出す。 */}
              {generation.inputError && <ErrorText>{generation.inputError}</ErrorText>}
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
            <RouteOutcome results={results} generation={generation} splice={splice} routeWeights={route.routeWeights} />
          </BottomSheet>
        </>
      )}
    </div>
  );
}
