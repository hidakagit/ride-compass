"use client";

import { formatJstHourMinute } from "@/lib/time";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs/Tabs";
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
  ClockIcon,
  RouteSpliceIcon,
  DownloadIcon,
  GenerateRoutesIcon,
  RedrawMapIcon,
  RouteIcon,
  RouteSettingsIcon,
} from "@/components/ui/icons/icons";
import BottomSheet, { clampSheetHeightVh, DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import LensControl from "@/features/map/LensControl/LensControl";
import ErrorText from "@/components/ErrorText/ErrorText";
import RouteForm, { type SettingsTab } from "@/features/route/RouteForm/RouteForm";
import RouteSettingsPanel from "@/features/route/RouteSettingsPanel/RouteSettingsPanel";
import HardFilterPanel from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import RouteAxisProfile from "@/features/route/RouteAxisProfile/RouteAxisProfile";
import SegmentWind from "@/features/route/SegmentWind/SegmentWind";
import RouteSplicePanel from "@/features/route/RouteSplicePanel/RouteSplicePanel";
import { useSpliceSession } from "@/features/route/useSpliceSession";
import { useGenerationConditions } from "@/features/route/useGenerationConditions";
import { useRouteGeneration } from "@/features/route/useRouteGeneration";
import AxisContributionBar from "@/components/AxisContributionBar/AxisContributionBar";
import WeatherPanel from "@/features/conditions/WeatherPanel/WeatherPanel";
import TodayOutlook from "@/features/conditions/TodayOutlook/TodayOutlook";
import WarningBadgeList, { type WarningFetchFailure } from "@/features/conditions/WarningBadge/WarningBadge";
import HeaderMenu from "@/components/HeaderMenu/HeaderMenu";
import RideConditionBar from "@/features/conditions/RideConditionBar/RideConditionBar";
import TravelBearingControl from "@/features/conditions/TravelBearingControl/TravelBearingControl";
import { useWeatherConditions } from "@/features/conditions/useWeatherConditions";
import { retryAxisCatalogFetch, useAxisCatalog } from "@/hooks/useAxisCatalog";
import { formatMaterialValue, MATERIAL_CATALOG, materialCatalogName } from "@/lib/axisMaterialsCatalog";
import { downloadGpx } from "@/features/route/gpxExport";
import { formatDurationShort } from "@/features/route/formatDuration";
import { baselineDistanceKm, loadBarHeightRatio } from "@/features/route/difficultyLoadBar";
import {
  extraDurationLabel,
  isSplicedRoute,
  fastestDurationSeconds,
  fastestRouteId,
} from "@/features/route/routeTabLabel";
import ComparisonPanel from "@/features/route/ComparisonPanel/ComparisonPanel";
import DifficultyProfile from "@/features/route/DifficultyProfile/DifficultyProfile";
import DebugConsole from "@/components/DebugConsole/DebugConsole";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useElementHeightCssVar } from "@/hooks/useElementHeightCssVar";
import { useLocation } from "@/hooks/useLocation";
import { useStoredState, useStoredBooleanState } from "@/hooks/useStoredState";
import { useRideConditions } from "@/features/conditions/useRideConditions";
import { useMapView } from "@/features/map/view/useMapView";
import type { RouteCandidate, RoutePreferenceWeights, SelectedRouteSegment } from "@/types/route";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { textVariants } from "@/components/ui/Text/Text";
import { cardVariants } from "@/components/ui/Card/Card";
import { dotVariants } from "@/components/ui/Dot/Dot";

// 経由地ルートのid（常に1件、「方位」という概念が無いためタブに順位番号を付けない）。
const NON_DIRECTIONAL_ROUTE_IDS = new Set([routeGenerateConfig.waypoints_route_id]);

function formatSegmentArrivalTime(iso: string | null): string {
  if (!iso) return "不明";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "不明";
  return formatJstHourMinute(date);
}

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

  const [routes, setRoutes] = useState<RouteCandidate[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  // 地図で押した区間。ある間、「ルート結果」はルート全体の代わりにこの区間の内訳を出す。候補を切り替える・
  // 作り直す・消すと外す（別の候補の区間を指したまま残らない）。
  const [selectedRouteSegment, setSelectedRouteSegment] = useState<SelectedRouteSegment | null>(null);
  // 「比較」タブを見ているか。選んだ候補は比較を見ている間も保ち、戻ったときにそのまま選ばれている。
  const [comparisonTabActive, setComparisonTabActive] = useState(false);
  // 生成に使われた重み（利用者の重みは生成後も変わりうる）。
  const [usedWeights, setUsedWeights] = useState<RoutePreferenceWeights | null>(null);
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
  const selectedCandidate = routes.find((r) => r.id === selectedRouteId) ?? null;
  const hasDetail = !!selectedCandidate?.segments && selectedCandidate.segments.length > 0;

  const mapView = useMapView({
    hasSelectedRoute: selectedCandidate !== null,
    hasDetail,
    ride: ride.ride,
    now: ride.departure.now,
    usedWeights,
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
    hasRoutes: routes.length > 0,
    onGenerated: ({ routes: generated, routePreference }) => {
      setRoutes(generated);
      // 最初に選ぶのは先頭（最も早く着く候補）。
      setSelectedRouteId(generated[0]?.id ?? null);
      // 比較を開いたまま生成したら新しい候補へ戻す（比較表が残ると、生成が効かなかったように見える）。
      setComparisonTabActive(false);
      // 候補が入れ替わると、押していた区間も意味を失う。
      setSelectedRouteSegment(null);
      setUsedWeights(routePreference);
      setUnseenOutcome(generated.length > 0 ? "fresh" : null);
    },
    onOutcome: notifyRouteOutcome,
  });

  // 生成したルート（候補・選択）だけを消す。地点のピンは消さない。実験スロットも地図へ重ね描きされるので一緒に消す
  // （押した見た目どおり地図が空になる）。
  const clearGeneration = generation.clear;
  const handleRoutesClear = useCallback(() => {
    setRoutes([]);
    setSelectedRouteId(null);
    setComparisonTabActive(false);
    setUsedWeights(null);
    setSelectedRouteSegment(null);
    clearGeneration();
  }, [clearGeneration]);

  // 区間の乗り換え。あれば「ルート結果」の同じ場所が編集面になる。
  const splice = useSpliceSession({
    routes,
    generatedInput: generation.generatedInput,
    hasSelectedRoute: selectedCandidate !== null,
    // 作ると、直前の生成の失敗の文言を残さない。
    onApplyStart: generation.clearNotice,
    onApplied: ({ routes: nextRoutes, selectedRouteId: nextSelectedRouteId }) => {
      setRoutes(nextRoutes);
      setSelectedRouteId(nextSelectedRouteId);
      setSelectedRouteSegment(null);
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

  // 「ルート結果」に候補が無いときの中身（生成前・生成中・失敗）。候補0件で生成前の案内へ戻ると、押したのに何も
  // 起きていないように見える。
  function renderRouteOutcomeEmptyState() {
    if (generation.running) {
      return <p className={textVariants({ variant: "hint" })}>{generation.progressLabel ?? "生成中..."}</p>;
    }
    if (generation.lastMessage) {
      return <ErrorText>{generation.lastMessage}</ErrorText>;
    }
    return <p className={textVariants({ variant: "hint" })}>「生成」を押すと候補がここに並びます</p>;
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

  // 候補1本への操作（合成・GPX出力）。その候補のタブの中身の先頭に置く。
  function renderCandidateActions(route: RouteCandidate) {
    return (
      <div className="flex items-center gap-1.5">
        {/* 合成（区間の乗り換え）の入口。乗り換えできない生成（周回・候補1件）では出さない。 */}
        {splice.canStart && (
          <Button
            size="iconLabel"
            onClick={() => {
              splice.start(route.id);
              // 区間の詳細の置き場は編集面に置き換わるため、選択を外す（地図に印だけが残らない）。
              setSelectedRouteSegment(null);
            }}
            aria-label="ルートを合成"
            title="区間を別の候補の道へ乗り換えて、新しいルートを作る"
          >
            <RouteSpliceIcon size={18} />
            合成
          </Button>
        )}
        <Button size="iconLabel" onClick={() => downloadGpx(route)} aria-label="GPX出力" title="GPXファイルで書き出す">
          <DownloadIcon size={18} />
          GPX
        </Button>
      </div>
    );
  }

  // 「ルート結果」の中身（デスクトップの区分・モバイルのシートの両方）。候補がある間に「生成」が通らなかったら、
  // 前の候補を残したまま先頭で知らせる（候補だけが並ぶと、作り直せたように見える）。
  function renderRouteOutcome() {
    if (routes.length === 0) return renderRouteOutcomeEmptyState();
    return (
      <>
        {generation.failure && <ErrorText>作り直せませんでした。{generation.failure}</ErrorText>}
        {renderRouteOutcomeSectionBody()}
      </>
    );
  }

  // 候補ごとのタブ＋「比較」タブの1列で、タブの切り替えが候補の切り替えを兼ねる。
  function renderRouteOutcomeSectionBody() {
    // 編集中は同じ場所が編集面になる（「ルート編集」という別の置き場を持たない）。元は1本に固定で、相手を
    // 選び直しても変わらない。
    if (splice.panel) return <RouteSplicePanel {...splice.panel} />;
    if (routes.length === 0) return null;

    const showComparisonTab = researchEnabled;
    const outerTabValue = comparisonTabActive ? "comparison" : (selectedRouteId ?? routes[0].id);
    const fastestSeconds = fastestDurationSeconds(routes);
    const fastestRouteIdInList = fastestRouteId(routes);
    // 難易度の帯の高さ1.0とする距離（面積が負荷になる）。一覧の行と候補の中身で同じ基準を使う。
    const loadBarBaselineKm = baselineDistanceKm(routes);
    // 道のりのグラフの横軸の右端。候補どうしで同じ物差しにし、面積（負荷）を見比べられるようにする。
    const longestDistanceKm = Math.max(0, ...routes.map((route) => route.distance_km));
    // 重みが0の軸を「未使用」と出す判定に使う（生成に使った重み）。
    const routeWeights = usedWeights ?? conditions.routePreference;

    return (
      <>
        {/* 作り直しの失敗を出している間は、それが前の条件の候補であることも伝えているので重ねない。 */}
        {generation.conditionsDirty && !generation.failure && (
          <p className="m-0 text-[length:var(--font-size-sm)] text-[var(--color-warning-strong)]">
            生成条件が変更されています
          </p>
        )}
        {generation.weightsNotApplied && (
          <p className="m-0 text-[length:var(--font-size-sm)] text-[var(--color-warning-strong)]">
            重み配分を反映できず、既定の配分で作りました。
          </p>
        )}
        {generation.destinationCorrected && (
          <p className="m-0 text-[length:var(--font-size-sm)] text-[var(--color-warning-strong)]">
            指定した地点は自転車で行けない場所だったため、近くのアクセス可能な地点へ補正しました。
          </p>
        )}
        <Tabs
          className="flex min-h-0 flex-row items-stretch gap-2 max-mobile:flex-auto"
          // 候補は横並びでは幅に収まらず溢れて消えるため、1行1候補の縦並びにし、行へ距離と難易度を並べる。
          orientation="vertical"
          value={outerTabValue}
          onValueChange={(value) => {
            setSelectedRouteSegment(null);
            if (value === "comparison") {
              setComparisonTabActive(true);
            } else {
              setComparisonTabActive(false);
              setSelectedRouteId(value);
            }
          }}
        >
          {/* 狭幅では下部シートの高さいっぱいまで伸ばし、はみ出す候補は一覧の中だけを縦スクロールさせる——一覧に固定の
              高さ上限を置くと、シートに余白があっても伸びずに触れない余白が残る。 */}
          <div className="flex w-48 flex-none items-stretch border-r border-[var(--color-border)]">
            <TabsList variant="side" className="max-mobile:min-h-0 max-mobile:overflow-y-auto" aria-label="ルート結果">
              {routes.map((route, index) => (
                <TabsTrigger key={route.id} value={route.id}>
                  {/* 見分けるための順位番号（並び順どおり）と距離。経由地のルートは常に1件なので番号の代わりに名前。 */}
                  <span className="truncate">
                    {NON_DIRECTIONAL_ROUTE_IDS.has(route.id) ? route.direction_label : `${index + 1}`}{" "}
                    {route.distance_km.toFixed(1)}km
                    {isSplicedRoute(route) && (
                      <span className="ml-1 font-normal text-[var(--color-muted-strong)]">合成</span>
                    )}
                    {/* 最速の候補はその所要時間を印付きで、他の候補はそこから何分余計にかかるか（見比べる場所に置く）。 */}
                    {route.id === fastestRouteIdInList && fastestSeconds !== null ? (
                      <span
                        className="ml-1 inline-flex items-center gap-0.5 font-normal text-[var(--color-muted-strong)]"
                        title="最速"
                      >
                        <span role="img" aria-label="最速" className="inline-flex">
                          <ClockIcon size={11} />
                        </span>
                        {formatDurationShort(fastestSeconds)}
                      </span>
                    ) : (
                      extraDurationLabel(route, fastestSeconds) && (
                        <span className="ml-1 font-normal text-[var(--color-muted-strong)]">
                          {extraDurationLabel(route, fastestSeconds)}
                        </span>
                      )
                    )}
                  </span>
                  {/* 総合難易度を数値と長さで。算出できなかった候補は「—」だけ（0と欠損を同じ見た目にしない）。 */}
                  <span className="flex flex-shrink-0 items-center justify-end gap-1">
                    <span
                      className="h-[calc(0.35rem*var(--load-bar-height-ratio,1))] w-6 flex-shrink-0 overflow-hidden rounded-[2px] bg-[var(--color-border)]"
                      style={
                        {
                          "--load-bar-height-ratio": String(loadBarHeightRatio(route.distance_km, loadBarBaselineKm)),
                        } as React.CSSProperties & { "--load-bar-height-ratio"?: string }
                      }
                    >
                      {route.overall_difficulty !== null && (
                        <span
                          className="block h-full rounded-l-[2px] bg-[var(--color-accent)] opacity-70"
                          style={{ width: `${route.overall_difficulty}%` }}
                        />
                      )}
                    </span>
                    <span className="font-normal text-[var(--color-muted-strong)] tabular-nums">
                      {route.overall_difficulty === null ? "—" : Math.round(route.overall_difficulty)}
                    </span>
                  </span>
                </TabsTrigger>
              ))}
              {showComparisonTab && <TabsTrigger value="comparison">比較</TabsTrigger>}
            </TabsList>
          </div>
          <div className="min-w-0 flex-auto">
            {routes.map((route) => (
              <TabsContent key={route.id} className="flex flex-col gap-2 data-[state=inactive]:hidden" value={route.id}>
                {renderCandidateActions(route)}
                {/* 道のりに沿った難易度。区間を選んでいる間も残す（動かして地点を選ぶ操作の置き場のため）。 */}
                {route.segments !== null && route.segments.length > 0 && (
                  <DifficultyProfile
                    segments={route.segments}
                    overallDifficulty={route.overall_difficulty}
                    axisOrder={axisCatalog.axes.map((axis) => axis.axisId)}
                    axisColors={axisCatalog.axisColors}
                    scaleKm={longestDistanceKm}
                    selected={selectedRouteSegment}
                    onSelect={setSelectedRouteSegment}
                  />
                )}
                {/* 押した区間がある間は、その区間の地点・到達予想・内訳を出す（区間は選んでいる候補にしか描かれない）。 */}
                {selectedRouteSegment ? (
                  <div className="flex flex-col gap-2">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="inline-flex items-baseline gap-2 text-[length:var(--font-size-md)] font-medium">
                        {selectedRouteSegment.segment.cumulative_distance_km.toFixed(1)} km地点
                        <span className={textVariants({ variant: "hint" })}>
                          到達予想 {formatSegmentArrivalTime(selectedRouteSegment.segment.estimated_arrival_time)}
                        </span>
                      </span>
                      <Button
                        variant="ghost"
                        size="bare"
                        className="px-1 text-[1.1rem]"
                        aria-label="区間の選択を解除"
                        onClick={() => setSelectedRouteSegment(null)}
                      >
                        ×
                      </Button>
                    </div>
                    <SegmentWind wind={selectedRouteSegment.segment.wind} />
                    <AxisContributionBar
                      axes={axisCatalog.axes}
                      contributions={selectedRouteSegment.segment.axis_contributions}
                      axisColors={axisCatalog.axisColors}
                    />
                    {researchEnabled && Object.keys(selectedRouteSegment.segment.material_values).length > 0 && (
                      <ul className={cn(textVariants({ variant: "hint" }), "m-0 flex list-none flex-col gap-0.5 p-0")}>
                        {/* 名前を引けない材料は出さない——材料idは内部名。 */}
                        {Object.entries(selectedRouteSegment.segment.material_values).flatMap(([materialId, value]) => {
                          const name = materialCatalogName(materialId, MATERIAL_CATALOG);
                          return name === undefined
                            ? []
                            : [
                                <li key={materialId}>
                                  {name}: {formatMaterialValue(materialId, value, MATERIAL_CATALOG)}
                                </li>,
                              ];
                        })}
                      </ul>
                    )}
                  </div>
                ) : (
                  <RouteAxisProfile
                    axes={axisCatalog.axes}
                    weights={routeWeights}
                    axisDifficulties={route.axis_difficulties}
                    axisContributions={route.axis_contributions}
                    axisRawValues={route.axis_raw_values}
                    materialValues={route.material_values}
                    materialCategoryShares={route.material_category_shares}
                    distanceKm={route.distance_km}
                    overallDifficulty={route.overall_difficulty}
                    difficultyLoad={route.difficulty_load ?? null}
                    estimatedDurationSeconds={route.estimated_duration_seconds ?? null}
                    windUnavailable={route.wind_unavailable}
                    missingTravelDataShare={route.missing_travel_data_share}
                    axisColors={axisCatalog.axisColors}
                  />
                )}
              </TabsContent>
            ))}
            {showComparisonTab && (
              // 開いていない間も描いておき、隠すだけにする。
              <TabsContent className="flex flex-col gap-2 data-[state=inactive]:hidden" value="comparison" forceMount>
                {/* 比較の軸は各スロットを作ったときの重みで選ぶ（いまの重みで絞ると、重みを0にした軸の差が比較から消える）。 */}
                <ComparisonPanel
                  slots={generation.experimentSlots}
                  axisLabels={axisCatalog.axisLabels}
                  axes={axisCatalog.axes.filter((axis) =>
                    generation.experimentSlots.some((slot) => (slot.conditions.route_preference[axis.axisId] ?? 0) > 0),
                  )}
                  materials={MATERIAL_CATALOG}
                />
              </TabsContent>
            )}
          </div>
        </Tabs>
      </>
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
                    routes.length > 0 ? (
                      <div className="flex flex-shrink-0 items-center gap-2">{renderRouteResultHeaderActions()}</div>
                    ) : undefined
                  }
                  open={outcomeOpen}
                  onOpenChange={setOutcomeOpen}
                >
                  {renderRouteOutcome()}
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
            routes={routes}
            {...splice.map}
            selectedRouteId={selectedRouteId}
            location={location}
            locationSource={locationSource}
            look={mapView.look}
            rideConditions={ride.ride}
            routePreference={conditions.routePreferenceToSend}
            // 実験スロットは「比較」を見ている間だけ地図へ重ねる（それ以外は選んだルートの色分けと紛らわしい）。
            experimentSlots={researchEnabled && comparisonTabActive ? generation.experimentSlots : []}
            selectedRouteSegment={selectedRouteSegment}
            onRouteSegmentSelect={(selection) => {
              if (!routeInspectionEnabled) return;
              setSelectedRouteSegment(selection);
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
            headerAction={routes.length > 0 ? renderRouteResultHeaderActions() : undefined}
            heightVh={mobileSheetHeightVh}
            onHeightChange={setWorkingSheetHeightVh}
            onHeightCommit={handleMobileSheetHeightCommit}
            autoFitHeight={!sheetHeightChosen}
          >
            {renderRouteOutcome()}
          </BottomSheet>
        </>
      )}
    </div>
  );
}
