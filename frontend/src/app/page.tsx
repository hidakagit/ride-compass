"use client";

import { formatJstHourMinute } from "@/lib/time";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs/Tabs";
import Disclosure from "@/components/Disclosure/Disclosure";
import { Button } from "@/components/ui/Button/Button";
import { cn } from "@/lib/cn";
import MapView, { type RouteFitObscuredPx } from "@/features/map/MapView/MapView";
import MapOverlayControls from "@/features/map/MapOverlayControls/MapOverlayControls";
import {
  ClearAllFiltersIcon,
  ClearAllLayersIcon,
  ClearRoutesIcon,
  RouteSpliceIcon,
  DownloadIcon,
  RedrawMapIcon,
  RouteIcon,
  RouteSettingsIcon,
} from "@/components/ui/icons/icons";
import BottomSheet, { clampSheetHeightVh, DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import LensControl from "@/features/map/LensControl/LensControl";
import { LENS_DIFFICULTY_ID, LENS_NONE_ID } from "@/lib/mapDisplay/routeStyleModes";
import ErrorText from "@/components/ErrorText/ErrorText";
import RouteForm, { type SettingsTab } from "@/features/route/RouteForm/RouteForm";
import { fixedRouteCount, useRouteFormSubmit, type RouteMode } from "@/features/route/RouteForm/useRouteFormSubmit";
import RouteSettingsPanel from "@/features/route/RouteSettingsPanel/RouteSettingsPanel";
import HardFilterPanel, { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import RouteAxisProfile from "@/features/route/RouteAxisProfile/RouteAxisProfile";
import RouteSplicePanel from "@/features/route/RouteSplicePanel/RouteSplicePanel";
import { haversineKm } from "@/lib/geoDistance";
import {
  buildSplicedShape,
  insertByDifficulty,
  stretchAlternativeGroups,
  stretchCoordinateRange,
  type StretchAlternative,
} from "@/features/route/routeSplice";
import AxisContributionBar from "@/components/AxisContributionBar/AxisContributionBar";
import WeatherPanel from "@/features/conditions/WeatherPanel/WeatherPanel";
import TodayOutlook from "@/features/conditions/TodayOutlook/TodayOutlook";
import WarningBadgeList from "@/features/conditions/WarningBadge/WarningBadge";
import HeaderMenu from "@/components/HeaderMenu/HeaderMenu";
import RideConditionBar from "@/features/conditions/RideConditionBar/RideConditionBar";
import TravelBearingControl from "@/features/conditions/TravelBearingControl/TravelBearingControl";
import { useWeatherConditions } from "@/features/conditions/useWeatherConditions";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { CLIENT_TUNING_IDS, clientTuningValue } from "@/lib/axisCatalog";
import { useMaterialCatalog } from "@/hooks/useMaterialCatalog";
import { syncHardFilterKeys } from "@/features/route/hardFilterSync";
import {
  buildGenerateRequest,
  generationConditionsKey,
  type GenerationInput,
} from "@/features/route/generationRequest";
import { routePreferenceToSend } from "@/features/route/routePreferenceSync";
import { formatMaterialValue, materialCatalogName } from "@/lib/axisMaterialsCatalog";
import { downloadGpx } from "@/features/route/gpxExport";
import { baselineDistanceKm, loadBarHeightRatio } from "@/features/route/difficultyLoadBar";
import {
  SPLICED_ROUTE_ID_PREFIX,
  extraDurationLabel,
  isSplicedRoute,
  fastestDurationSeconds,
  fastestRouteId,
} from "@/features/route/routeTabLabel";
import ComparisonPanel from "@/features/route/ComparisonPanel/ComparisonPanel";
import DebugConsole from "@/components/DebugConsole/DebugConsole";
import { debugLog } from "@/lib/debugLog";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useElementHeightCssVar } from "@/hooks/useElementHeightCssVar";
import { useLocation } from "@/hooks/useLocation";
import { useStoredState, useStoredBooleanState, useStoredJsonState } from "@/hooks/useStoredState";
import { useDepartureTime } from "@/features/conditions/useDepartureTime";
import { useMapView } from "@/features/map/view/useMapView";
import { generateRoutes, type GenerationProgress } from "@/features/route/routeApi";
import type {
  Coordinates,
  PinRole,
  HardFilterOverride,
  RouteCandidate,
  RoutePreferenceWeights,
  SelectedRouteSegment,
} from "@/types/route";
import { EXPERIMENT_SLOT_COLORS, MAX_EXPERIMENT_SLOTS, type ExperimentSlot } from "@/types/experimentSlot";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { textVariants } from "@/components/ui/Text/Text";
import { cardVariants } from "@/components/ui/Card/Card";
import { dotVariants } from "@/components/ui/Dot/Dot";

// 経由地ルートのid（常に1件、「方位」という概念が無いためタブに順位番号を付けない）。
const NON_DIRECTIONAL_ROUTE_IDS = new Set(["route-waypoints"]);

function formatSegmentArrivalTime(iso: string | null): string {
  if (!iso) return "不明";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "不明";
  return formatJstHourMinute(date);
}

const MAX_DISTANCE_KM = routeGenerateConfig.max_distance_km;

const GENERATE_OPEN_STORAGE_KEY = "ridecompass:generate-open";
const OUTCOME_OPEN_STORAGE_KEY = "ridecompass:outcome-open";
// モバイルの下部シートの高さ。シートは1つずつしか開かないため、1つの値を共有する。
const MOBILE_SHEET_HEIGHT_STORAGE_KEY = "ridecompass:mobile-sheet-height-vh";
const WEIGHT_OVERRIDE_ENABLED_STORAGE_KEY = "ridecompass:weight-override-enabled";
const ROUTE_PREFERENCE_STORAGE_KEY = "ridecompass:route-preference";
const HARD_FILTERS_STORAGE_KEY = "ridecompass:hard-filters";
// 「条件」タブの入力値。場所（目的地・経由地のピン）は持たない——行くたびに変わるうえ、
// 古いピンが残っていると気づかないまま生成してしまう。
const ROUTE_MODE_STORAGE_KEY = "ridecompass:route-mode";
const DISTANCE_STORAGE_KEY = "ridecompass:distance-km";
const MAX_ROUTES_STORAGE_KEY = "ridecompass:max-routes";
// 走行条件のうち想定速度だけを保つ（出発時刻・走行方位は行くたびに変わる）。
const ASSUMED_SPEED_STORAGE_KEY = "ridecompass:assumed-speed-kmh";

// 区分の見出しのDOM id（デスクトップの区分・モバイルのシート）。
const GENERATE_SECTION_TITLE_ID = "generate-section-title";
const OUTCOME_SECTION_TITLE_ID = "outcome-section-title";
const ROUTE_SETTINGS_SHEET_TITLE_ID = "route-settings-sheet-title";
const ROUTE_OUTCOME_SHEET_TITLE_ID = "route-outcome-sheet-title";

type MobileSheet = "routeSettings" | "routeOutcome" | null;

/** ルート生成の進み方。同時に成り立つのは1つだけ。 */
type Generation =
  { status: "idle"; message: string | null } | { status: "running"; progress: GenerationProgress | null };
const GENERATION_IDLE: Generation = { status: "idle", message: null };

/** 区間の乗り換えの進み方。 */
type SpliceTask = { status: "idle"; error: string | null } | { status: "previewing" } | { status: "applying" };
const SPLICE_IDLE: SpliceTask = { status: "idle", error: null };

/** 失敗の文言だけを消す（処理中なら何もしない）。 */
const withoutError = (task: SpliceTask): SpliceTask => (task.status === "idle" ? SPLICE_IDLE : task);

/** 区間の乗り換えの編集1回ぶん。 */
interface SpliceSession {
  /** 編集の元にした候補。 */
  routeId: string;
  /** 適用した乗り換えを積み上げる。各要素の範囲は「適用した時点の経路」に対する位置のため、
   * 途中だけを外すことはできない（戻せるのは直前の1手）。 */
  applied: StretchAlternative[];
  /** 「差分を見る」で評価した結果。組み合わせをキーに覚え、選び直して戻ったときに投げ直さない
   * （生成APIには回数の上限がある）。 */
  previews: Record<string, RouteCandidate>;
  /** 評価と適用は同時に走らない。失敗は押した場所（編集パネル）に出す。 */
  task: SpliceTask;
}
const NO_ALTERNATIVES: StretchAlternative[] = [];

function spliceFailureMessage(error: unknown): string {
  return error instanceof Error ? error.message : "組み合わせたルートの評価に失敗しました";
}

/** 1グループが持てる選択肢の数。`spliceFeatureIndex`がこの位取りで位置を1つの数へ畳むため、超えると隣の
 *  グループの選択肢として黙って引き戻される。実際には届かないが、届いたとき黙って壊れないよう弾く。 */
const SPLICE_OPTIONS_PER_GROUP = 100;

/** 乗り換え候補の帯のid。グループの位置と選択肢の位置を1つの数にして、地図のタップから
 *  どの選択肢かを引き戻せるようにする。 */
const spliceFeatureIndex = (groupIndex: number, optionIndex: number) => {
  if (optionIndex >= SPLICE_OPTIONS_PER_GROUP) {
    throw new Error(`乗り換えの選択肢が1グループ${SPLICE_OPTIONS_PER_GROUP}件の上限を超えた（index=${optionIndex}）`);
  }
  return groupIndex * SPLICE_OPTIONS_PER_GROUP + optionIndex;
};

/** モバイルの下部タブ（シートと同じ並び）。 */
const MOBILE_TABS = [
  { sheet: "routeSettings", label: "ルート設定", Icon: RouteSettingsIcon },
  { sheet: "routeOutcome", label: "ルート結果", Icon: RouteIcon },
] as const;

export default function Home() {
  const { location, locationSource, locationReady, locating, locateError, handleLocateMe, setManualLocation } =
    useLocation();

  const axisCatalog = useAxisCatalog();
  const { materials: materialCatalog } = useMaterialCatalog();

  const [routes, setRoutes] = useState<RouteCandidate[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  // 区間の乗り換えの編集。あれば「ルート結果」の同じ場所が編集面になる。始めると空から始まり、抜けると
  // 中身ごと消える（前回の編集の残りを次へ持ち込まない）。
  const [splice, setSplice] = useState<SpliceSession | null>(null);
  const updateSplice = (next: (current: SpliceSession) => SpliceSession) =>
    setSplice((current) => (current === null ? null : next(current)));
  const editingRouteId = splice?.routeId ?? null;
  const appliedAlternatives = splice?.applied ?? NO_ALTERNATIVES;
  const spliceTask = splice?.task ?? SPLICE_IDLE;
  // 「新しいルートを作る」の実行中。stateと違い同じタスク内ですぐ読めるので、連打の2回目をここで止める。
  const applyingRef = useRef(false);
  const setSpliceTask = (task: SpliceTask) => updateSplice((current) => ({ ...current, task }));
  // 地図で押した区間。ある間、「ルート結果」はルート全体の代わりにこの区間の内訳を出す。候補を切り替える・
  // 作り直す・消すと外す（別の候補の区間を指したまま残らない）。
  const [selectedRouteSegment, setSelectedRouteSegment] = useState<SelectedRouteSegment | null>(null);
  // 「比較」タブを見ているか。選んだ候補は比較を見ている間も保ち、戻ったときにそのまま選ばれている。
  const [comparisonTabActive, setComparisonTabActive] = useState(false);
  // 新しい結果が出て、まだ「ルート結果」を開いていない（モバイルのタブの合図）。
  const [hasUnseenResults, setHasUnseenResults] = useState(false);
  // ルート生成。実行中は順番待ちか実行中かと経過時間をボタンへ出し、終わった後は直近の案内（候補0件の
  // 理由・失敗の文言）を「ルート結果」欄に残す。
  const [generation, setGeneration] = useState<Generation>(GENERATION_IDLE);
  const loading = generation.status === "running";

  // 経由地（通る順）。
  const [waypoints, setWaypoints] = useState<Coordinates[]>([]);
  const handleWaypointRemove = useCallback((index: number) => {
    setWaypoints((prev) => prev.filter((_, i) => i !== index));
  }, []);
  const handleWaypointMove = useCallback((index: number, point: Coordinates) => {
    setWaypoints((prev) => prev.map((current, i) => (i === index ? point : current)));
  }, []);
  const handleWaypointsClear = useCallback(() => setWaypoints([]), []);

  // 目的地（あれば片道のルート）。
  const [destination, setDestination] = useState<Coordinates | null>(null);
  // 地図のタップで置ける地点の役割（1つだけ）。無い間は地図を触ってもピンは増えない。
  const [armedPinRole, setArmedPinRole] = useState<PinRole | null>(null);

  // 周回か目的地か。切り替えても経由地・目的地は消さない（周回の間は地図に出さず送らないだけで、戻れば復元される）。
  const [routeMode, setRouteMode] = useStoredState<RouteMode>(ROUTE_MODE_STORAGE_KEY, "loop", {
    serialize: (mode) => mode,
    deserialize: (raw) => (raw === "loop" || raw === "destination" ? raw : null),
  });
  const handleRouteModeChange = useCallback(
    (mode: RouteMode) => {
      setRouteMode(mode);
      if (mode === "destination") {
        // 何も置いていなければ、次のタップで目的地を置けるようにする。既に置いてあれば、次のタップは経由地の
        // 追加かもしれないので自動では武装しない（目的地が意図せず上書きされる）。
        setArmedPinRole(destination === null && waypoints.length === 0 ? "destination" : null);
      } else {
        setArmedPinRole(null);
      }
    },
    [destination, waypoints.length, setRouteMode],
  );

  // 武装中の役割の地点として地図のタップを受ける。経由地だけは置いたあとも武装を続ける
  // （続けて何地点も置くのが普通の使い方で、1つ置くたびに押し直させない）。
  const handlePinPlace = useCallback(
    (role: PinRole, point: Coordinates) => {
      if (role === "origin") {
        setManualLocation(point);
        setArmedPinRole(null);
        return;
      }
      if (role === "destination") {
        setDestination(point);
        setArmedPinRole(null);
        return;
      }
      setWaypoints((prev) => [...prev, point]);
    },
    [setManualLocation],
  );
  const handleDestinationClear = useCallback(() => setDestination(null), []);
  // 行を押して武装する。置いてある地点から武装しても値は残し、次のタップで置き換える（外してから置き直させない）。
  const handleArmPinRole = useCallback((role: PinRole | null) => setArmedPinRole(role), []);

  // 距離の入力（文字列のまま）。ここで持つのは、表示中の候補を作った条件と比べて「生成条件が変更されています」を出すため。
  const [distanceInput, setDistanceInput] = useStoredState(DISTANCE_STORAGE_KEY, "30", {
    serialize: (value) => value,
    // 保存値は画面の範囲内の数値だけを受け入れる（範囲が縮んだ後でも、範囲外の距離が復元されて送られない）。
    deserialize: (raw) => {
      const parsed = Number(raw);
      return Number.isFinite(parsed) && parsed >= 1 && parsed <= routeGenerateConfig.max_distance_km ? raw : null;
    },
  });
  // 候補数（文字列のまま、送るときに数へ）。
  const [maxRoutesInput, setMaxRoutesInput] = useStoredState(
    MAX_ROUTES_STORAGE_KEY,
    String(routeGenerateConfig.default_max_routes),
    {
      serialize: (value) => value,
      deserialize: (raw) => {
        const parsed = Number(raw);
        return Number.isInteger(parsed) && parsed >= 1 && parsed <= routeGenerateConfig.max_routes ? raw : null;
      },
    },
  );
  // 「ルート生成」の検証と送信（handleGenerateは関数宣言なので後ろで定義していても読める）。
  const routeFormSubmit = useRouteFormSubmit({
    distance: distanceInput,
    maxRoutes: maxRoutesInput,
    routeMode,
    waypointCount: waypoints.length,
    destinationSet: destination !== null,
    onGenerate: handleGenerate,
  });
  // 想定速度（km/h）。区間の通過予定時刻・到達予想時刻の基準になるため、どのモードでも送る。
  const [assumedSpeedKmh, setAssumedSpeedKmh] = useStoredState<number>(
    ASSUMED_SPEED_STORAGE_KEY,
    routeGenerateConfig.default_assumed_speed_kmh,
    {
      serialize: String,
      deserialize: (raw) => {
        const parsed = Number(raw);
        return Number.isInteger(parsed) &&
          parsed >= routeGenerateConfig.min_assumed_speed_kmh &&
          parsed <= routeGenerateConfig.max_assumed_speed_kmh
          ? parsed
          : null;
      },
    },
  );
  // 表示中の候補を作ったときの条件。
  const [generatedConditions, setGeneratedConditions] = useState<{
    /** 送った入力から導いた比較のキー。いまのフォームから同じ関数で作ったキーと比べる。 */
    key: string;
    /** 目的地が道路網から外れていて、backendが最寄りの行ける地点へ補正したか。 */
    destinationCorrected: boolean;
    /** 送った入力そのもの。乗り換えで合成した経路も同じ条件で評価する（同じ並びへ入るため、条件が違うと
     * 比べられない値で順位が決まる）。返ってきた条件（`conditions`）でなく入力を持つのは、そちらが
     * 塗る軸（`lens_axis_id`）を含まないため。 */
    input: GenerationInput;
    /** 生成に使われた重み（利用者の重みは生成後も変わりうる）。 */
    routePreference: RoutePreferenceWeights;
  } | null>(null);
  const generatedRoutePreference = generatedConditions?.routePreference ?? null;

  // 重みを上書きして送るか。OFFの間は重みを送らず、backendの既定で探す。重みを操作するとONになる。
  const [weightOverrideEnabled, setWeightOverrideEnabled] = useStoredBooleanState(
    WEIGHT_OVERRIDE_ENABLED_STORAGE_KEY,
    false,
  );
  // 初期値は空。既定の重みは実行時の軸カタログが配り、送る直前に当てる（ビルド時の写しを初期値にすると、
  // 軸の増減が次のデプロイまで届かない）。
  const [routePreference, setRoutePreference] = useStoredJsonState<RoutePreferenceWeights>(
    ROUTE_PREFERENCE_STORAGE_KEY,
    {},
  );
  // 除外の設定。常に送る。保存値に今は無い項目が混じっていても、読むときに今の項目へ揃える。
  const [hardFilters, setHardFilters] = useStoredState<HardFilterOverride>(
    HARD_FILTERS_STORAGE_KEY,
    DEFAULT_HARD_FILTERS,
    {
      serialize: (value) => JSON.stringify(value),
      deserialize: (raw) => {
        try {
          return syncHardFilterKeys(JSON.parse(raw) as HardFilterOverride, DEFAULT_HARD_FILTERS);
        } catch {
          return null;
        }
      },
    },
  );

  // 実験スロット: 研究モードの生成結果の直近数件（地図の重ね描き・比較表）。
  const [experimentSlots, setExperimentSlots] = useState<ExperimentSlot[]>([]);

  // 生成したルート（候補・選択）だけを消す。地点のピンは消さない。実験スロットも地図へ重ね描きされるので一緒に消す
  // （押した見た目どおり地図が空になる）。
  const handleRoutesClear = useCallback(() => {
    setRoutes([]);
    setSelectedRouteId(null);
    setComparisonTabActive(false);
    setGeneratedConditions(null);
    setExperimentSlots([]);
    setSelectedRouteSegment(null);
  }, []);

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

  // 区間の乗り換えはEdge idの集合の演算だけで求まる（軸の計算式は持たない）。編集中の候補は`routes`から引く
  // ——候補が入れ替わったときに編集だけが残ると、地図の地点の編集・候補の選択が黙って効かないままになる。
  const editingRoute = routes.find((route) => route.id === editingRouteId) ?? null;
  // 以下は地図へ渡す値。描画のたびに作り直すと地図の反映があらゆる再描画で走る（候補1本に数千件のEdge id）。
  const candidateShapes = useMemo(
    () =>
      routes.map((route) => ({
        id: route.id,
        edgeIds: route.edge_ids,
        shape: {
          coordinates: route.geometry.coordinates as GeoJSON.Position[],
          edgePointOffsets: route.edge_point_offsets,
          nodeIds: route.node_ids,
        },
      })),
    [routes],
  );
  // いまの組み合わせ（元＋適用した乗り換え）。次に選べる区間も評価へ送るEdge列もこれを見る（乗り換えた先の道の
  // 分かれ道へそのまま進める）。
  const splicedShape = useMemo(() => {
    if (!editingRoute) return null;
    const shapeOf = (candidateId: string) => candidateShapes.find((item) => item.id === candidateId)?.shape;
    return buildSplicedShape(
      {
        edgeIds: editingRoute.edge_ids,
        coordinates: editingRoute.geometry.coordinates as GeoJSON.Position[],
        edgePointOffsets: editingRoute.edge_point_offsets,
        nodeIds: editingRoute.node_ids,
      },
      appliedAlternatives,
      shapeOf,
    );
  }, [editingRoute, appliedAlternatives, candidateShapes]);
  // 区間を割る下限（km）。**引けないときは乗り換えの候補を作らない**——ここで既定を
  // 作ると、較正したのとは別の切り方（下限なし＝共有地点すべてで割る）で黙って動く。
  const minStretchKm = clientTuningValue(axisCatalog, CLIENT_TUNING_IDS.minStretchKm);
  const spliceGroups = useMemo(
    () =>
      splicedShape && minStretchKm !== undefined
        ? stretchAlternativeGroups(
            splicedShape.edgeIds,
            candidateShapes.filter((item) => item.id !== editingRouteId),
            // 座標も渡すと、2本が交わる地点でも区間を割れる（Edge idだけでは丸ごとの入れ替えにしかならない）。
            { baseShape: splicedShape, minSplitLengthKm: minStretchKm },
          )
        : [],
    [splicedShape, candidateShapes, editingRouteId, minStretchKm],
  );
  // 地図の帯は相手側の形（適用した道はいまの経路の一部なので出ない）。indexは地図のタップから選択肢を引き戻す。
  const spliceStretchFeatures = useMemo(
    () =>
      spliceGroups.flatMap((group, groupIndex) =>
        group.options.flatMap((option, optionIndex) => {
          const target = routes.find((route) => route.id === option.candidateId);
          if (!target) return [];
          const range = stretchCoordinateRange(target.edge_point_offsets, option.targetStretch);
          if (!range) return [];
          const coordinates = (target.geometry.coordinates as GeoJSON.Position[]).slice(range.start, range.end + 1);
          if (coordinates.length < 2) return [];
          return [{ index: spliceFeatureIndex(groupIndex, optionIndex), coordinates }];
        }),
      ),
    [spliceGroups, routes],
  );

  // 適用した順で識別する。同じ位置でも積み上げた経緯が違えば別の経路になるため順番を含める。
  const spliceChoiceKey = appliedAlternatives
    .map((item, index) => `${index}:${item.candidateId}:${item.stretch.start}-${item.stretch.end}`)
    .join("|");
  const splicePreview = splice?.previews[spliceChoiceKey] ?? null;
  // 地図の帯をタップしたら、その道へ乗り換える。
  const handleSpliceStretchSelect = useCallback(
    (index: number) => {
      const option =
        spliceGroups[Math.floor(index / SPLICE_OPTIONS_PER_GROUP)]?.options[index % SPLICE_OPTIONS_PER_GROUP];
      if (!option) return;
      updateSplice((current) => ({
        ...current,
        applied: [...current.applied, option],
        task: withoutError(current.task),
      }));
    },
    [spliceGroups],
  );
  const hasDetail = !!selectedCandidate?.segments && selectedCandidate.segments.length > 0;

  const isMobile = useIsMobile();

  // 「ルート設定」のタブ。タブ列は見出し行、中身は本文に描くため、両方を囲むここで持つ。
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("generate");

  // 地図でできることは、いま見ているパネルが持つ操作だけにする（地図を触った副作用で地点が変わらない）。
  // 「ルート設定」の条件タブ＝地点を置く・動かす・消す、「ルート結果」＝候補の切り替えと区間の詳細、
  // 編集中＝乗り換え先の選択だけ。モバイルはシート、デスクトップはパネルを畳んでおらず区分が開いていることが
  // 「見ているか」に当たる（畳むと区分の開閉は保ったまま中身が見えなくなる）。
  const routeSettingsActive = isMobile ? mobileSheet === "routeSettings" : !sidebarCollapsed && generateOpen;
  const routeOutcomeActive = isMobile ? mobileSheet === "routeOutcome" : !sidebarCollapsed && outcomeOpen;
  const pointEditingEnabled = routeSettingsActive && settingsTab === "generate" && editingRoute === null;
  const routeInspectionEnabled = routeOutcomeActive && editingRoute === null;
  const pinPlacementArmedRole = routeMode === "destination" && pointEditingEnabled ? armedPinRole : null;

  const handleRouteSelectFromMap = useCallback(
    (routeId: string) => {
      if (!routeInspectionEnabled) return;
      setSelectedRouteSegment(null);
      setSelectedRouteId(routeId);
    },
    [routeInspectionEnabled],
  );

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

  // 走行条件。地図の見え方・生成リクエスト・道の詳細が同じ値を読む。
  const [travelBearingDeg, setTravelBearingDeg] = useState(0);
  const departure = useDepartureTime();
  const rideConditions = useMemo(
    () => ({ bearingDeg: travelBearingDeg, at: departure.at, speedKmh: assumedSpeedKmh }),
    [travelBearingDeg, departure.at, assumedSpeedKmh],
  );
  const mapView = useMapView({
    hasSelectedRoute: selectedCandidate !== null,
    hasDetail,
    ride: rideConditions,
    now: departure.now,
    usedWeights: generatedRoutePreference,
  });

  // モバイルのタブ。同じタブをもう一度押したら閉じる。
  const handleMobileTabClick = useCallback(
    (sheet: Exclude<MobileSheet, null>) => {
      setMobileSheet((prev) => (prev === sheet ? null : sheet));
      // 「ルート結果」タブを開いたら、新着結果の合図は役目を終える。
      if (sheet === "routeOutcome") setHasUnseenResults(false);
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

  // 今日の見通し・最寄りの実測・警報の類（位置が決まってから、位置が変わるたびに取る）。
  const {
    weather,
    weatherLoading,
    weatherError,
    amedas,
    amedasLoading,
    amedasError,
    warningBadgeItems,
    warningFetchFailures,
  } = useWeatherConditions(location, locationReady);

  // いまのフォームから生成の入力を組み立てる。生成と「条件が変わったか」の判定が同じ関数を通るので、送る値を
  // 足したときに比較の側へ足し忘れない。`destinationOverride`はbackendが補正した目的地（目的地から導く距離も
  // 一緒に組み直すため、ここを通す）。
  const buildCurrentGenerationInput = useCallback(
    (distanceKm: number, destinationOverride?: Coordinates): GenerationInput => {
      const effectiveDestination = destinationOverride ?? destination;
      const destinationModePoints =
        routeMode === "destination" ? [...waypoints, ...(effectiveDestination ? [effectiveDestination] : [])] : [];
      return {
        origin: location,
        // 目的地モードの距離は、置いた点の最も遠いものより必ず長くする（backendは探索範囲と「点が遠すぎないか」の
        // 検査にこの距離を使う）。
        distanceKm:
          routeMode === "destination" && destinationModePoints.length > 0
            ? Math.min(
                MAX_DISTANCE_KM,
                Math.ceil(destinationModePoints.reduce((max, p) => Math.max(max, haversineKm(location, p)), 0)) + 1,
              )
            : distanceKm,
        distanceToleranceKm: routeGenerateConfig.default_distance_tolerance_km,
        maxRoutes: fixedRouteCount(routeMode, waypoints.length) ?? Number(maxRoutesInput),
        assumedSpeedKmh,
        startTime: departure.at,
        startTimePinned: departure.pinned,
        hardFilters,
        // 軸カタログが届くまでは塗る軸を送らない（backendは知らない軸を黙って無視する）。
        lensAxisId:
          axisCatalog.loaded && mapView.lens !== LENS_NONE_ID && mapView.lens !== LENS_DIFFICULTY_ID
            ? mapView.lens
            : null,
        routePreference: routePreferenceToSend(
          routePreference,
          { loaded: axisCatalog.loaded, defaultWeights: axisCatalog.defaultWeights },
          weightOverrideEnabled,
        ),
        waypoints: routeMode === "destination" ? waypoints : [],
        destination: routeMode === "destination" ? effectiveDestination : null,
      };
    },
    [
      routeMode,
      waypoints,
      destination,
      location,
      maxRoutesInput,
      assumedSpeedKmh,
      departure.at,
      departure.pinned,
      hardFilters,
      mapView.lens,
      weightOverrideEnabled,
      axisCatalog.loaded,
      axisCatalog.defaultWeights,
      routePreference,
    ],
  );

  // 表示中の候補を作った条件と、いまのフォームがずれているか（変えただけでは何も起きないことを知らせる）。
  const conditionsDirty =
    generatedConditions != null &&
    routes.length > 0 &&
    generationConditionsKey(buildCurrentGenerationInput(Number(distanceInput))) !== generatedConditions.key;

  // 選んだ組み合わせをbackendで評価する（frontendは経路を組み立てるだけ）。差分の表示と「作る」で同じものを使い、
  // 評価済みなら投げ直さない。
  async function evaluateSplicedRoute(): Promise<RouteCandidate | null> {
    if (!editingRoute || appliedAlternatives.length === 0 || !splicedShape) return null;
    const cached = splice?.previews[spliceChoiceKey];
    if (cached) return cached;
    // 表示中の候補を作った条件で評価する（いまのフォームだと、生成後に重みを変えた1本だけ別の条件で並ぶ）。
    const generatedInput = generatedConditions?.input;
    if (!generatedInput) return null;
    const { routes: candidates } = await generateRoutes({
      ...buildGenerateRequest(generatedInput),
      spliced_edge_ids: splicedShape.edgeIds,
    });
    const spliced = candidates[0] ?? null;
    if (spliced)
      updateSplice((current) => ({ ...current, previews: { ...current.previews, [spliceChoiceKey]: spliced } }));
    return spliced;
  }

  // 作る前に、この組み合わせで何が変わるかを見る（評価はbackendでしか出せないので、押したときだけ投げる）。
  async function handlePreviewSplice() {
    if (!editingRoute || appliedAlternatives.length === 0 || spliceTask.status === "previewing") return;
    setSpliceTask({ status: "previewing" });
    try {
      const spliced = await evaluateSplicedRoute();
      setSpliceTask(spliced ? SPLICE_IDLE : { status: "idle", error: "組み合わせたルートを評価できませんでした" });
    } catch (error) {
      setSpliceTask({ status: "idle", error: spliceFailureMessage(error) });
    }
  }

  async function handleApplySplice() {
    // 連打で2本入るのを防ぐ（ボタンを押せなくするのは再描画を待つため、その前の2回目は通る）。
    if (applyingRef.current) return;
    if (!editingRoute || appliedAlternatives.length === 0) return;
    // 前提の確認は印を立てる前に済ませる（立ててから抜けると、印が立ったままこの操作が二度と効かなくなる）。
    const generatedInput = generatedConditions?.input;
    if (!generatedInput) return;
    applyingRef.current = true;
    setSpliceTask({ status: "applying" });
    setGeneration((current) => (current.status === "idle" ? GENERATION_IDLE : current));
    try {
      const spliced = await evaluateSplicedRoute();
      if (!spliced) {
        setSpliceTask({ status: "idle", error: "組み合わせたルートを評価できませんでした" });
        return;
      }
      // 全部を1つの候補の道へ乗り換えると、既にある候補そのものになる。そのときは並べずにその候補を選ぶ。
      const sameRoute = routes.find((route) => route.edge_ids.join(",") === spliced.edge_ids.join(","));
      // 生成した候補と同じ並びの規約へ入れる（見分けはタブの名前）。候補数の上限では切り詰めない（上限は生成が何本
      // 探すかで、作った組み合わせを押し出す理由が無い）。
      const unique = { ...spliced, id: `${SPLICED_ROUTE_ID_PREFIX}-${routes.length}` };
      if (!sameRoute) setRoutes(insertByDifficulty(routes, unique));
      setSelectedRouteId(sameRoute ? sameRoute.id : unique.id);
      setSelectedRouteSegment(null);
      setSplice(null);
      notifyRouteOutcome();
    } catch (error) {
      setSpliceTask({ status: "idle", error: spliceFailureMessage(error) });
    } finally {
      applyingRef.current = false;
    }
  }

  async function handleGenerate(distanceKm: number) {
    setGeneration({ status: "running", progress: null });
    let message: string | null = null;
    try {
      const generationInput = buildCurrentGenerationInput(distanceKm);
      const {
        routes: candidates,
        conditions,
        noCandidatesReason,
      } = await generateRoutes(buildGenerateRequest(generationInput), (progress) =>
        setGeneration({ status: "running", progress }),
      );
      // backendが目的地を補正したら、地図のピンも実際に使われた地点へ合わせる。
      if (conditions.corrected_destination) {
        setDestination(conditions.corrected_destination);
      }
      setRoutes(candidates);
      setSelectedRouteId(candidates[0]?.id ?? null);
      // 比較を開いたまま生成したら新しい候補へ戻す（比較表が残ると、生成が効かなかったように見える）。
      setComparisonTabActive(false);
      // 候補が入れ替わると、乗り換えの編集も押していた区間も意味を失う。
      setSplice(null);
      setSelectedRouteSegment(null);
      setHasUnseenResults(candidates.length > 0);
      // 補正があったら補正後の地点で入力を組み直す（ピンも動かしたので、直後に「条件が変わった」にならない）。
      const generatedInput = conditions.corrected_destination
        ? buildCurrentGenerationInput(distanceKm, conditions.corrected_destination)
        : generationInput;
      setGeneratedConditions({
        key: generationConditionsKey(generatedInput),
        destinationCorrected: Boolean(conditions.corrected_destination),
        input: generatedInput,
        routePreference: conditions.route_preference,
      });
      if (candidates.length === 0) {
        message = noCandidatesReason ?? "条件に合うルート候補が見つかりませんでした。距離を変えて試してください。";
        notifyRouteOutcome();
      } else if (researchEnabled) {
        // 研究モードの生成だけを実験スロットへ残す。代表は難易度が最小の候補（後で選び直しても変えない）。
        setExperimentSlots((prev) => {
          const next: ExperimentSlot = {
            id: `slot-${conditions.generated_at}-${Math.random().toString(36).slice(2, 8)}`,
            color: EXPERIMENT_SLOT_COLORS[0],
            conditions,
            topCandidate: candidates[0],
          };
          // 色は並びの位置で決める（最新が先頭の色）。
          return [next, ...prev]
            .slice(0, MAX_EXPERIMENT_SLOTS)
            .map((slot, i) => ({ ...slot, color: EXPERIMENT_SLOT_COLORS[i % EXPERIMENT_SLOT_COLORS.length] }));
        });
      }
    } catch (error) {
      message = error instanceof Error ? error.message : "不明なエラーが発生しました";
      debugLog("api:route", "ルート生成ハンドラで例外", { error: message }, "error");
      notifyRouteOutcome();
    } finally {
      setGeneration({ status: "idle", message });
    }
  }

  // 生成の結果（候補も失敗も）は「ルート結果」でしか見えないので知らせる。デスクトップは区分を開き、モバイルは
  // タブのドットで知らせる（シートは勝手に開かない）。
  const notifyRouteOutcome = useCallback(() => {
    setOutcomeOpen(true);
    setHasUnseenResults(true);
  }, [setOutcomeOpen]);

  // 入力の検証の誤りも「ルート生成」を押した結果として同じく知らせる。
  useEffect(() => {
    if (routeFormSubmit.error) notifyRouteOutcome();
  }, [routeFormSubmit.error, notifyRouteOutcome]);

  const generationProgress = generation.status === "running" ? generation.progress : null;
  const generationProgressLabel =
    generationProgress?.status === "queued"
      ? "順番待ち..."
      : generationProgress?.status === "running"
        ? `生成中...(${Math.round(generationProgress.elapsedMs / 1000)}秒経過)`
        : undefined;

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
        {conditionsDirty && (
          <span
            className={dotVariants({ tone: "warning" })}
            role="img"
            aria-label="生成条件が変更されています"
            title="生成条件が変更されています"
          />
        )}
        <Button variant="primary" size="sm" type="button" disabled={loading} onClick={routeFormSubmit.handleSubmit}>
          {loading ? (generationProgressLabel ?? "生成中...") : "ルート生成"}
        </Button>
      </div>
    );
  }

  // 「ルート設定」の中身（デスクトップの区分・モバイルのシートの両方）。生成の結果・誤りはここに出さない（ボタンは
  // 本文を畳んだままでも押せるため）。出し先は「ルート結果」に1つにする。
  function renderRouteSectionBody() {
    return (
      <RouteForm
        distance={distanceInput}
        onDistanceChange={setDistanceInput}
        maxRoutes={maxRoutesInput}
        onMaxRoutesChange={setMaxRoutesInput}
        routeMode={routeMode}
        onRouteModeChange={handleRouteModeChange}
        waypointCount={waypoints.length}
        onWaypointsClear={handleWaypointsClear}
        destinationSet={destination !== null}
        onDestinationClear={handleDestinationClear}
        originManual={locationSource === "manual"}
        originLocated={locationSource !== "default"}
        onOriginReset={handleLocateMe}
        armedPinRole={armedPinRole}
        onArmPinRole={handleArmPinRole}
        weightsPanel={
          <RouteSettingsPanel
            routePreference={routePreference}
            onRoutePreferenceChange={setRoutePreference}
            overrideEnabled={weightOverrideEnabled}
            onOverrideEnabledChange={setWeightOverrideEnabled}
          />
        }
        exclusionsPanel={<HardFilterPanel hardFilters={hardFilters} onHardFiltersChange={setHardFilters} />}
      />
    );
  }

  // 「ルート結果」に候補が無いときの中身（生成前・生成中・失敗）。候補0件で生成前の案内へ戻ると、押したのに何も
  // 起きていないように見える。
  function renderRouteOutcomeEmptyState() {
    if (loading) {
      return <p className={textVariants({ variant: "hint" })}>{generationProgressLabel ?? "生成中..."}</p>;
    }
    const failure = routeFormSubmit.error ?? (generation.status === "idle" ? generation.message : null);
    if (failure) {
      return <ErrorText>{failure}</ErrorText>;
    }
    return <p className={textVariants({ variant: "hint" })}>「ルート生成」を押すと候補がここに並びます</p>;
  }

  // 「ルート結果」の見出しの操作（編集・GPX出力・クリア）。候補がある間だけ呼ばれる。
  function renderRouteResultHeaderActions() {
    return (
      <>
        {/* 編集の入口。乗り換えできない生成（周回・候補1件）では出さない。 */}
        {canSpliceDisplayedRoute() && editingRoute === null && (
          <Button
            size="icon"
            onClick={() => {
              if (!selectedCandidate) return;
              setSplice({ routeId: selectedCandidate.id, applied: [], previews: {}, task: SPLICE_IDLE });
              // 区間の詳細の置き場は編集面に置き換わるため、選択を外す（地図に印だけが残らない）。
              setSelectedRouteSegment(null);
            }}
            title="このルートを編集（区間の乗り換え）"
            aria-label="このルートを編集"
          >
            <RouteSpliceIcon size={18} />
          </Button>
        )}
        <Button
          size="icon"
          disabled={!selectedCandidate}
          onClick={() => selectedCandidate && downloadGpx(selectedCandidate)}
          title="GPX出力"
          aria-label="GPX出力"
        >
          <DownloadIcon size={18} />
        </Button>
        <Button size="icon" onClick={handleRoutesClear} title="ルートをクリア" aria-label="ルートをクリア">
          <ClearRoutesIcon size={18} />
        </Button>
      </>
    );
  }

  // 「ルート結果」の中身。候補ごとのタブ＋「比較」タブの1列で、タブの切り替えが候補の切り替えを兼ねる。
  function renderRouteOutcomeSectionBody() {
    // 編集中は同じ場所が編集面になる（「ルート編集」という別の置き場を持たない）。
    if (editingRoute) return renderRouteEditSectionBody();
    if (routes.length === 0) return null;

    const showComparisonTab = researchEnabled;
    const outerTabValue = comparisonTabActive ? "comparison" : (selectedRouteId ?? routes[0].id);
    const fastestSeconds = fastestDurationSeconds(routes);
    const fastestRouteIdInList = fastestRouteId(routes);
    // 難易度の帯の高さ1.0とする距離（面積が負荷になる）。一覧の行と候補の中身で同じ基準を使う。
    const loadBarBaselineKm = baselineDistanceKm(routes);
    // 重みが0の軸を「未使用」と出す判定に使う（生成に使った重み）。
    const routeWeights = generatedRoutePreference ?? routePreference;

    return (
      <>
        {conditionsDirty && (
          <p className="m-0 text-[length:var(--font-size-sm)] text-[var(--color-warning-strong)]">
            生成条件が変更されています
          </p>
        )}
        {generatedConditions?.destinationCorrected && (
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
          <div className="flex w-40 flex-none items-stretch border-r border-[var(--color-border)]">
            <TabsList variant="side" aria-label="ルート結果">
              {routes.map((route, index) => (
                <TabsTrigger key={route.id} value={route.id}>
                  {/* 見分けるための順位番号（並び順どおり）と距離。経由地のルートは常に1件なので番号の代わりに名前。 */}
                  <span className="truncate">
                    {NON_DIRECTIONAL_ROUTE_IDS.has(route.id) ? route.direction_label : `${index + 1}`}{" "}
                    {route.distance_km.toFixed(1)}km
                    {isSplicedRoute(route) && (
                      <span className="ml-1 font-normal text-[var(--color-muted-strong)]">合成</span>
                    )}
                    {/* 最速の候補と、そこから何分余計にかかるか（見比べる場所に置く）。 */}
                    {route.id === fastestRouteIdInList ? (
                      <span className="ml-1 font-normal text-[var(--color-muted-strong)]">最速</span>
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
                    <AxisContributionBar
                      axes={axisCatalog.axes}
                      contributions={selectedRouteSegment.segment.axis_contributions}
                      axisColors={axisCatalog.axisColors}
                    />
                    {researchEnabled && Object.keys(selectedRouteSegment.segment.material_values).length > 0 && (
                      <ul className={cn(textVariants({ variant: "hint" }), "m-0 flex list-none flex-col gap-0.5 p-0")}>
                        {/* 名前を引けない材料は出さない——材料idは内部名。 */}
                        {Object.entries(selectedRouteSegment.segment.material_values).flatMap(([materialId, value]) => {
                          const name = materialCatalogName(materialId, materialCatalog);
                          return name === undefined
                            ? []
                            : [
                                <li key={materialId}>
                                  {name}: {formatMaterialValue(materialId, value, materialCatalog)}
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
                    loadBarHeightRatio={loadBarHeightRatio(route.distance_km, loadBarBaselineKm)}
                    estimatedDurationSeconds={route.estimated_duration_seconds ?? null}
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
                  slots={experimentSlots}
                  axisLabels={axisCatalog.axisLabels}
                  axes={axisCatalog.axes.filter((axis) =>
                    experimentSlots.some((slot) => (slot.conditions.route_preference[axis.axisId] ?? 0) > 0),
                  )}
                  materials={materialCatalog}
                />
              </TabsContent>
            )}
          </div>
        </Tabs>
      </>
    );
  }

  // 編集できるのは目的地のルートだけ（周回は乗り換えると起点へ戻れる保証が無い）。表示中の候補を作った生成で見る
  // （いまのピンで見ると、周回へ切り替えた後も編集が出て、評価の要求が目的地無しで弾かれる）。
  function canSpliceDisplayedRoute(): boolean {
    return Boolean(generatedConditions?.input.destination) && routes.length > 1 && selectedCandidate !== null;
  }

  // 「ルート結果」が編集モードのときの中身。元は1本に固定で、相手を選び直しても変わらない。
  function renderRouteEditSectionBody() {
    if (editingRoute === null) return null;
    return (
      <RouteSplicePanel
        displayed={editingRoute}
        onCancel={() => {
          setSplice(null);
        }}
        appliedCount={appliedAlternatives.length}
        hasAlternatives={spliceStretchFeatures.length > 0}
        onUndo={() => {
          updateSplice((current) => ({
            ...current,
            applied: current.applied.slice(0, -1),
            task: withoutError(current.task),
          }));
        }}
        onReset={() => {
          updateSplice((current) => ({ ...current, applied: [], task: withoutError(current.task) }));
        }}
        preview={splicePreview}
        previewing={spliceTask.status === "previewing"}
        onPreview={handlePreviewSplice}
        onApply={handleApplySplice}
        axes={axisCatalog.axes}
        axisColors={axisCatalog.axisColors}
        error={spliceTask.status === "idle" ? spliceTask.error : null}
        applying={spliceTask.status === "applying"}
      />
    );
  }

  return (
    <div className="flex h-dvh flex-col">
      <header
        className="flex flex-shrink-0 flex-nowrap items-center gap-2 overflow-x-auto border-b border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        title="風向・風速はルート候補の評価に使われます"
      >
        {/* 風と今日の見通しは左端に固定して常に見せる。入り切らないときに隠れるのは警報の側。 */}
        <div className="left-0 flex flex-shrink-0 items-center gap-2 sticky z-1 bg-[var(--color-surface)]">
          <WeatherPanel amedas={amedas} loading={amedasLoading} error={amedasError} />
          <TodayOutlook weather={weather} loading={weatherLoading} error={weatherError} />
        </div>
        <div className="ml-auto flex flex-shrink-0 items-center gap-2">
          <WarningBadgeList items={warningBadgeItems} failures={warningFetchFailures} />
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
                  {routes.length > 0 ? renderRouteOutcomeSectionBody() : renderRouteOutcomeEmptyState()}
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
            spliceStretches={spliceStretchFeatures}
            splicedRoute={splicedShape ? splicedShape.coordinates : null}
            onSpliceStretchSelect={handleSpliceStretchSelect}
            selectedRouteId={selectedRouteId}
            location={location}
            locationSource={locationSource}
            look={mapView.look}
            rideConditions={rideConditions}
            // 実験スロットは「比較」を見ている間だけ地図へ重ねる（それ以外は選んだルートの色分けと紛らわしい）。
            experimentSlots={researchEnabled && comparisonTabActive ? experimentSlots : []}
            selectedRouteSegment={selectedRouteSegment}
            onRouteSegmentSelect={(selection) => {
              if (!routeInspectionEnabled) return;
              setSelectedRouteSegment(selection);
            }}
            onRouteSelect={handleRouteSelectFromMap}
            waypoints={routeMode === "destination" ? waypoints : []}
            onWaypointRemove={handleWaypointRemove}
            onWaypointMove={handleWaypointMove}
            destination={routeMode === "destination" ? destination : null}
            onDestinationClear={handleDestinationClear}
            armedPinRole={pinPlacementArmedRole}
            pointEditingEnabled={pointEditingEnabled}
            onPinPlace={handlePinPlace}
            measureRouteFitObscuredPx={measureRouteFitObscuredPx}
          />

          <LensControl {...mapView.lensControl} />

          <MapOverlayControls {...mapView.overlayControls} />

          {/* 地図の下の中央に「まとめて元に戻す」操作を並べる（レイヤーのON/OFFと凡例の絞り込みは別の状態）。 */}
          <div
            ref={bottomControlRowRef}
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

          <TravelBearingControl value={travelBearingDeg} onChange={setTravelBearingDeg} />

          {/* 走行条件（出発時刻・想定速度）は走行方位の直下に積む。出発時刻は気象レイヤーの表示時刻と同じもの。 */}
          <div className="pointer-events-none absolute top-[calc(var(--map-ctrl-stack-top)+var(--map-ctrl-button-size)+var(--map-ctrl-stack-gap))] right-[var(--map-ctrl-margin)] z-[var(--z-map-control)]">
            <RideConditionBar
              departureTime={departure.at}
              onDepartureTimeChange={departure.setAt}
              onDepartureNow={departure.followNow}
              speedKmh={assumedSpeedKmh}
              onSpeedKmhChange={setAssumedSpeedKmh}
            />
          </div>

          <Button
            variant="float"
            size="bare"
            shape="pill"
            onClick={handleLocateMe}
            disabled={locating}
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
                onClick={() => handleMobileTabClick(sheet)}
              >
                <Icon />
                <span className="text-[0.62rem] leading-none whitespace-nowrap">{label}</span>
                {/* 条件が変わった（生成前）と、新しい結果が出た（生成後）の両方を同じ点で知らせる。 */}
                {sheet === "routeOutcome" && (conditionsDirty || hasUnseenResults) && (
                  <span
                    aria-hidden="true"
                    className={cn(dotVariants({ tone: "warning" }), "absolute top-1.5 right-2.5")}
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
              fitKey={`${settingsTab}:${routeMode}`}
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
            {routes.length > 0 ? renderRouteOutcomeSectionBody() : renderRouteOutcomeEmptyState()}
          </BottomSheet>
        </>
      )}
    </div>
  );
}
