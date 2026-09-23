"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import Disclosure from "@/components/Disclosure/Disclosure";
import { Button } from "@/components/ui/Button/Button";
import MapView, { type RouteFitObscuredPx } from "@/components/Map/MapView";
import MapOverlayControls from "@/components/MapOverlayControls/MapOverlayControls";
import {
  ClearAllFiltersIcon,
  ClearAllLayersIcon,
  ClearRoutesIcon,
  RouteSpliceIcon,
  DownloadIcon,
  RedrawMapIcon,
  RouteIcon,
  RouteSettingsIcon,
} from "@/components/Map/icons";
import BottomSheet, { clampSheetHeightVh, DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import LensControl from "@/components/LensControl/LensControl";
import { LENS_DIFFICULTY_ID, LENS_NONE_ID } from "@/components/Map/routeStyleModes";
import ErrorText from "@/components/ErrorText/ErrorText";
import RouteForm, { type RouteMode, type SettingsTab } from "@/components/RouteForm/RouteForm";
import { useRouteFormSubmit } from "@/components/RouteForm/useRouteFormSubmit";
import RouteSettingsPanel from "@/components/RouteSettingsPanel/RouteSettingsPanel";
import HardFilterPanel, { DEFAULT_HARD_FILTERS } from "@/components/RouteSettingsPanel/HardFilterPanel";
import RouteAxisProfile from "@/components/RouteAxisProfile/RouteAxisProfile";
import RouteSplicePanel from "@/components/RouteSplicePanel/RouteSplicePanel";
import { haversineKm } from "@/lib/geoDistance";
import {
  buildSplicedShape,
  insertByDifficulty,
  stretchAlternativeGroups,
  stretchCoordinateRange,
  type StretchAlternative,
} from "@/lib/routeSplice";
import AxisContributionBar from "@/components/RouteAxisProfile/AxisContributionBar";
import WeatherPanel from "@/components/WeatherPanel/WeatherPanel";
import TodayOutlook from "@/components/TodayOutlook/TodayOutlook";
import WarningBadgeList from "@/components/WarningBadge/WarningBadge";
import HeaderMenu from "@/components/HeaderMenu/HeaderMenu";
import RideConditionBar from "@/components/RideConditionBar/RideConditionBar";
import TravelBearingControl from "@/components/TravelBearingControl/TravelBearingControl";
import { useWeatherConditions } from "@/hooks/useWeatherConditions";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { CLIENT_TUNING_IDS, clientTuningValue } from "@/lib/axisCatalog";
import { useMaterialCatalog } from "@/hooks/useMaterialCatalog";
import { syncHardFilterKeys } from "@/lib/hardFilterSync";
import { buildGenerateRequest, generationConditionsKey, type GenerationInput } from "@/lib/generationRequest";
import { routePreferenceToSend } from "@/lib/routePreferenceSync";
import { formatMaterialValue, materialCatalogName } from "@/lib/axisMaterialsCatalog";
import { downloadGpx } from "@/lib/gpxExport";
import { baselineDistanceKm, loadBarHeightRatio } from "@/lib/difficultyLoadBar";
import {
  SPLICED_ROUTE_ID_PREFIX,
  extraDurationLabel,
  isSplicedRoute,
  fastestDurationSeconds,
  fastestRouteId,
} from "@/lib/routeTabLabel";
import ComparisonPanel from "@/components/ComparisonPanel/ComparisonPanel";
import DebugConsole from "@/components/DebugConsole/DebugConsole";
import { debugLog } from "@/lib/debugLog";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useElementHeightCssVar } from "@/hooks/useElementHeightCssVar";
import { useIsomorphicLayoutEffect } from "@/hooks/useIsomorphicLayoutEffect";
import { useLocation } from "@/hooks/useLocation";
import { useStoredState, useStoredBooleanState, useStoredJsonState } from "@/hooks/useStoredState";
import { useDepartureTime } from "@/hooks/useDepartureTime";
import { useMapView } from "@/features/map/view/useMapView";
import { generateRoutes, type GenerationProgress } from "@/services/routeApi";
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
import styles from "./page.module.css";

// 経由地ルートのid（常に1件、「方位」という概念が無いためタブに順位番号を付けない）。
const NON_DIRECTIONAL_ROUTE_IDS = new Set(["route-waypoints"]);

// 区間クリック詳細（selectedRouteSegment）の到達予想時刻表示のフォーマット。
function formatSegmentArrivalTime(iso: string | null): string {
  if (!iso) return "不明";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "不明";
  return date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}

// backend/app/api/routers/routes.py: RouteGenerateRequest.distance_km（Field(gt=0,
// le=MAX_ROUTE_DISTANCE_KM)）と一致させる（目的地モードの自動算出値もこの上限で
// クランプする、handleGenerate参照）。backend側の唯一の情報源（export_openapi.py:
// ROUTE_GENERATE_CONFIG_PATH）から導出する。
const MAX_DISTANCE_KM = routeGenerateConfig.max_distance_km;

// 目的地モードでは距離をユーザーに入力させず、地図上の経由地・目的地から自動算出する
// （backend/app/domain/geo.py: haversine_distance_kmと同じ球面距離の簡易実装。フロントは
// 既存の距離計算ユーティリティを持たないためここに最小実装する）。
const GENERATE_OPEN_STORAGE_KEY = "ridecompass:generate-open";
const OUTCOME_OPEN_STORAGE_KEY = "ridecompass:outcome-open";
// モバイル下部シートの高さ。シートは排他表示のため1つの値を共有する
// （BottomSheetのheightVh props参照）。
const MOBILE_SHEET_HEIGHT_STORAGE_KEY = "ridecompass:mobile-sheet-height-vh";
// ルート設定（系統A、RouteSettingsPanelが操作する評価の設定）。
const WEIGHT_OVERRIDE_ENABLED_STORAGE_KEY = "ridecompass:weight-override-enabled";
const ROUTE_PREFERENCE_STORAGE_KEY = "ridecompass:route-preference";
const HARD_FILTERS_STORAGE_KEY = "ridecompass:hard-filters";
// 「条件」タブの入力値。場所（目的地・経由地のピン）は持たない——行くたびに変わるうえ、
// 古いピンが残っていると気づかないまま生成してしまう。
const ROUTE_MODE_STORAGE_KEY = "ridecompass:route-mode";
const DISTANCE_STORAGE_KEY = "ridecompass:distance-km";
const MAX_ROUTES_STORAGE_KEY = "ridecompass:max-routes";
// 走行条件（地図上のRideConditionBar）のうち想定速度だけを持つ。巡航速度は利用者固有の
// 安定した値だが、出発時刻・走行方位は行くたびに変わる。
const ASSUMED_SPEED_STORAGE_KEY = "ridecompass:assumed-speed-kmh";

// 「ルートを作る」セクション見出しのDOM id。デスクトップの<summary>専用（モバイルは
// 「ルート設定」「ルート結果」の2タブへ分割しているため、専用の
// ROUTE_SETTINGS_SHEET_TITLE_ID/ROUTE_OUTCOME_SHEET_TITLE_IDを別途持つ）。
const GENERATE_SECTION_TITLE_ID = "generate-section-title";
const OUTCOME_SECTION_TITLE_ID = "outcome-section-title";
// モバイルの「ルート設定」「ルート結果」シート見出しのDOM id。
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
  /** 「差分を見る」で評価した結果。組み合わせをキーに覚える——選び直して戻ったときに投げ直さない
   * （生成APIは1分10回の上限があり、評価自体も温で1秒前後かかる）。 */
  previews: Record<string, RouteCandidate>;
  /** 評価（差分を見る）と適用（新しいルートを作る）は同時に走らない。失敗は「ルート結果」欄の
   * 空状態には出ない（候補がある間は描かれない）ため、押した場所＝編集パネルに出す。 */
  task: SpliceTask;
}
const NO_ALTERNATIVES: StretchAlternative[] = [];

function spliceFailureMessage(error: unknown): string {
  return error instanceof Error ? error.message : "組み合わせたルートの評価に失敗しました";
}

/** 1グループが持てる選択肢の数。`spliceFeatureIndex`がこの位取りでグループと選択肢の位置を
 *  1つの数へ畳むため、**超えると隣のグループの選択肢として引き戻される**（例外も表示の乱れも出ず、
 *  黙って別の区間へ乗り換わる）。候補は生成数の上限（画面で最大8件）で決まるため実際には
 *  届かないが、届いたときに黙って壊れないよう組み立てる側で弾く。 */
const SPLICE_OPTIONS_PER_GROUP = 100;

/** 乗り換え候補の帯のid。グループの位置と選択肢の位置を1つの数にして、地図のタップから
 *  どの選択肢かを引き戻せるようにする。 */
const spliceFeatureIndex = (groupIndex: number, optionIndex: number) => {
  if (optionIndex >= SPLICE_OPTIONS_PER_GROUP) {
    throw new Error(`乗り換えの選択肢が1グループ${SPLICE_OPTIONS_PER_GROUP}件の上限を超えた（index=${optionIndex}）`);
  }
  return groupIndex * SPLICE_OPTIONS_PER_GROUP + optionIndex;
};

export default function Home() {
  const { location, locationSource, locationReady, locating, locateError, handleLocateMe, setManualLocation } =
    useLocation();

  // 出発地点は地図上の赤ピン自体をドラッグ&ドロップして動かす（MapView.tsx: onOriginSet、
  // マーカーのdragendから呼ばれる）。「現在地に戻す」は既存の「現在地に移動」ボタン
  // （handleLocateMe）がそのまま兼ねるため、専用のボタン・武装状態は持たない。
  // 軸カタログ（ramp表示・凡例チップグルーピングを含む）を先頭で取得する。
  // axisVisibility/secondaryAxisCasingLayerIds（下記）・地図チップ組み立てが参照するため、
  // それらより前で宣言する必要がある。
  const axisCatalog = useAxisCatalog();
  // 比較パネル（研究モード）の材料値行（material_values）のラベル・単位表記に使う
  // （ComparisonPanel.tsx参照）。
  const { materials: materialCatalog } = useMaterialCatalog();

  const [routes, setRoutes] = useState<RouteCandidate[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  // 区間の乗り換え。比較相手と、相手の道を選んだ区間の位置。
  // 区間の位置はstretchesの添字で持つ——edge_idsの位置で持つと、候補が入れ替わったときに
  // 別の場所を指したまま残る。
  // 編集（区間の乗り換え）。nullなら「ルート結果」は通常の一覧、非nullなら同じ場所が編集面に
  // なる（独立したタブにすると、どのルートを編集しているのかを選び直す形になる）。編集を始めると
  // 空から始まり、抜けると中身ごと消える——前回の編集の残りを次へ持ち込まない。
  const [splice, setSplice] = useState<SpliceSession | null>(null);
  const updateSplice = (next: (current: SpliceSession) => SpliceSession) =>
    setSplice((current) => (current === null ? null : next(current)));
  const editingRouteId = splice?.routeId ?? null;
  const appliedAlternatives = splice?.applied ?? NO_ALTERNATIVES;
  const spliceTask = splice?.task ?? SPLICE_IDLE;
  // 「新しいルートを作る」の実行中フラグ。stateと違い同じタスク内で即座に読めるため、
  // 連打の2回目をここで止める。
  const applyingRef = useRef(false);
  const setSpliceTask = (task: SpliceTask) => updateSplice((current) => ({ ...current, task }));
  // 地図上でクリックされた区間（MapView.tsx: handleRouteSegmentClickがクリック地点の
  // 座標とともに設定するcontrolled state）。non-nullの間、「ルート結果」タブはルート
  // 全体の内訳の代わりにこの区間の内訳を表示する（下記renderRouteOutcomeSectionBody
  // 参照）。候補タブの切り替え・再生成・ルートクリアのいずれでも古い区間を選択したままに
  // しないよう、該当箇所でnullへ戻す。
  const [selectedRouteSegment, setSelectedRouteSegment] = useState<SelectedRouteSegment | null>(null);
  // ルート結果パネルの外側タブは、候補ごとのタブ＋「比較」タブという1段のフラットな
  // タブ列。outerタブの選択値はselectedRouteId（候補タブ選択時）とこのフラグ（比較タブ
  // 選択時）を
  // 組み合わせて求める——selectedRouteId自体は比較タブを見ている間も「最後に見ていた候補」
  // を保持し続け、地図の色分け対象・selectedCandidate等の既存の使われ方を変えない
  // （比較タブから候補タブへ戻ったとき、見ていた候補がそのまま選択された状態に戻る）。
  const [comparisonTabActive, setComparisonTabActive] = useState(false);
  // モバイルで軸調整→再生成した直後、「ルート結果」タブへの視覚的な誘導に使う状態。
  // conditionsDirtyの通知ドットは「生成前に条件が変わった」ことを知らせる目的で、生成
  // 完了と同時に消える仕様のため、「新しい結果が用意できた」ことを知らせる別の目的には
  // 使えない。この状態は生成成功時にtrue、「ルート結果」タブを開いたらfalseにする
  // （handleGenerate/handleMobileTabClick参照）。
  const [hasUnseenResults, setHasUnseenResults] = useState(false);
  // ルート生成。実行中は待ち(queued)/実行中(running)の別と経過時間をボタン文言へ出し
  // （progressはどちらかが確定するまでnull）、終わった後は直近の案内（候補0件の理由・失敗の
  // 文言）を「ルート結果」欄に残す。
  const [generation, setGeneration] = useState<Generation>(GENERATION_IDLE);
  const loading = generation.status === "running";

  // 地図クリックで指定する経由地（起点→経由地1→...→起点の順で通過する単一経路を
  // 生成する）。指定があれば周回探索は行わない（handleGenerate参照）。
  const [waypoints, setWaypoints] = useState<Coordinates[]>([]);
  const handleWaypointRemove = useCallback((index: number) => {
    setWaypoints((prev) => prev.filter((_, i) => i !== index));
  }, []);
  const handleWaypointMove = useCallback((index: number, point: Coordinates) => {
    setWaypoints((prev) => prev.map((current, i) => (i === index ? point : current)));
  }, []);
  const handleWaypointsClear = useCallback(() => setWaypoints([]), []);

  // 目的地（最大1点）。指定時は起点に戻らず目的地で終わる片道ルートになる
  // （handleGenerate参照）。
  const [destination, setDestination] = useState<Coordinates | null>(null);
  // 地図のタップで置ける地点の役割。**どれか1つだけ**が置ける状態になり、その間だけ地図の
  // タップがピンの配置として扱われる（MapView.tsx: armedPinRole）。nullの間は地図を触っても
  // ピンは増えない——役割を選ばずに置けると、地図を見ているだけのつもりの操作で経由地が増える。
  const [armedPinRole, setArmedPinRole] = useState<PinRole | null>(null);

  // 周回（距離指定）/目的地（地図タップで経由地・目的地を指定）モードの切り替え。
  // 経由地・目的地の操作はRouteForm（距離入力・生成ボタンと同じ場所）に統合されている。
  // モード切り替え自体は経由地・目的地の値を消さない（周回モードへ切り替えても地図上のピンは
  // 保持し、目的地モードへ戻れば復元される。地図への表示・追加受付だけがモードで変わる、
  // handleGenerate/MapView.tsxのpointEditingEnabled参照）。
  const [routeMode, setRouteMode] = useStoredState<RouteMode>(ROUTE_MODE_STORAGE_KEY, "loop", {
    serialize: (mode) => mode,
    deserialize: (raw) => (raw === "loop" || raw === "destination" ? raw : null),
  });
  const handleRouteModeChange = useCallback(
    (mode: RouteMode) => {
      setRouteMode(mode);
      if (mode === "destination") {
        // 目的地・経由地とも未指定のまま目的地モードへ入った場合、行を押さなくても次の
        // タップで目的地を置けるようにする。既に目的地・経由地があるときは自動で武装しない
        // ——次のタップの意図が「経由地の追加」である可能性があり、武装したままだと意図せず
        // 目的地が上書きされてしまうため。
        setArmedPinRole(destination === null && waypoints.length === 0 ? "destination" : null);
      } else {
        // 周回モードへ切り替えたら武装を持ち越さない（地図にピンを置く操作自体が無い）。
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
  // 地図上の候補線から候補を選ぶ。一覧（縦タブ）での切り替えと同じく、前の候補で
  // クリックしていた区間の選択は引き継がない（別候補のedge_idを指したまま残るため）。
  const handleDestinationClear = useCallback(() => setDestination(null), []);
  // 行の操作で武装する（同じ行をもう一度押すと解除）。設定済みの地点から武装しても値は
  // 残したままで、地図タップが置き換えになる——生成後に目的地を変えたいとき、解除してから
  // 指定し直す手順を踏ませないため。解除は行の✕が担う。
  const handleArmPinRole = useCallback((role: PinRole | null) => setArmedPinRole(role), []);

  // 距離入力（文字列のまま保持）。RouteForm内ではなくここで持つのは、表示中の候補を
  // 生成したときの条件と現在のフォーム値を比較して「生成条件が変更されています」ヒントを
  // 出すため。
  const [distanceInput, setDistanceInput] = useStoredState(DISTANCE_STORAGE_KEY, "30", {
    serialize: (value) => value,
    // 保存値はUIの範囲内の数値だけを受け入れる（範囲外・壊れた値は既定値のまま扱う）。
    // スライダーの範囲が縮んだ後でも、範囲外の距離が復元されて送信されることはない。
    deserialize: (raw) => {
      const parsed = Number(raw);
      return Number.isFinite(parsed) && parsed >= 1 && parsed <= routeGenerateConfig.max_distance_km ? raw : null;
    },
  });
  // 周回候補の上限件数（backend: RouteGenerateRequest.max_routes、1〜15）。距離入力と
  // 同じくstring stateのまま保持し、送信時にNumber化する。目的地モードでは経由地が無い
  // 場合のみ意味を持つ（経由地を伴うとbackendが常に1件へ固定し無視する、RouteForm.tsx参照）。
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
  // 「ルート生成」ボタン（「ルート設定」見出し行、RouteForm.tsxのタブとは別位置）の
  // 検証・送信ロジック。handleGenerateは関数宣言のため巻き上げにより以降で定義されていても
  // 参照できる。
  const routeFormSubmit = useRouteFormSubmit({
    distance: distanceInput,
    maxRoutes: maxRoutesInput,
    routeMode,
    waypointCount: waypoints.length,
    destinationSet: destination !== null,
    onGenerate: handleGenerate,
  });
  // 仮定巡航速度（backend: RouteGenerateRequest.assumed_speed_kmh、km/h）。区間の通過予定
  // 時刻（探索時の風の時刻選択）・到達予想時刻の基準になるため全モードで送る。
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
  // 表示中の候補を生成したときの条件スナップショット。重みは値の組をJSON文字列で比較する
  // （フィールド比較の列挙より差分検知の漏れが出にくい）。
  const [generatedConditions, setGeneratedConditions] = useState<{
    // 生成に実際に送ったpayloadから導出した比較キー（lib/generationRequest.ts:
    // generationConditionsKey）。現在のフォーム値から同じ関数で作ったキーと突き合わせる
    // だけでconditionsDirtyが決まるため、比較したいフィールドを個別に持たない。
    key: string;
    // 経由地の無い目的地ルートで、指定した目的地がメインの道路網から孤立していたため
    // backendが最寄りのアクセス可能な地点へ補正した場合true
    // （conditions.corrected_destination）。表示中の候補がこの補正を経て生成された
    // ことを示すヒントの表示条件に使う（比較には使わない）。
    destinationCorrected: boolean;
    // 生成に実際に送った入力そのもの。区間の乗り換えで合成した
    // 経路も**同じ条件で**評価するために使う——合成結果は素の結果と本質的に区別せず、
    // 同じ並びへ差し込まれるため、条件が違うと比較できない値で順位が決まる。
    // エコー（`conditions`）ではなく入力を持つのは、エコーが`lens_axis_id`を含まない
    // ため（区間表示用の軸評価が候補ごとに食い違う）。
    input: GenerationInput;
    // 生成に実際に使われた重み（backendが`conditions.route_preference`として返す値）。
    // 利用者の重みは生成後も編集されうるため、表示中のルートを評価した重みはこちらを読む。
    routePreference: RoutePreferenceWeights;
  } | null>(null);
  const generatedRoutePreference = generatedConditions?.routePreference ?? null;

  // 評価重みのリクエスト上書き（研究インターフェース改善 §10-1/4）。overrideEnabled=falseの間は
  // 生成リクエストからroute_preferenceを省略し、既存挙動（既定値）を完全に維持する
  // （一般ユーザーには影響しない）。route_preference/routePreference自体は一般向けルート
  // 設定画面（RouteSettingsPanel）とも共有する状態で、withAutoEnableにより、どちらの
  // パネルを操作してもこのフラグが自動でONになる。
  const [weightOverrideEnabled, setWeightOverrideEnabled] = useStoredBooleanState(
    WEIGHT_OVERRIDE_ENABLED_STORAGE_KEY,
    false,
  );
  // 初期値は空。既定重みは実行時の軸カタログが配り、送信直前に
  // `syncRoutePreferenceKeys`が当てる。**ビルド時の写しを初期値にしない**——
  // 軸の増減が次のデプロイまで届かず、利用者が設定していない重みで走ることになる。
  const [routePreference, setRoutePreference] = useStoredJsonState<RoutePreferenceWeights>(
    ROUTE_PREFERENCE_STORAGE_KEY,
    {},
  );
  // 0次ハードフィルタ。一般向けルート設定画面（RouteSettingsPanel）が
  // 常時操作するため、weightOverrideEnabledのような別トグルは持たず常にリクエストへ含める
  // （既定値はDEFAULT_HARD_FILTERS＝backendのDEFAULT_HARD_FILTERSと同じ全フィルタ有効で、
  // 省略時と挙動が一致するため常時送信して問題ない）。同じパネルが操作する
  // routePreferenceと揃えて保存する。保存値に未知のキーが混じっていても、送信前に
  // syncHardFilterKeysがbackendの現在のキー集合へ整合させる。
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

  // 実験スロット（研究インターフェース改善 §10-3）: デバッグモード中の生成結果を条件付きで
  // 直近MAX_EXPERIMENT_SLOTS件だけメモリ内に保持し、地図重ね描き・比較表に使う。
  const [experimentSlots, setExperimentSlots] = useState<ExperimentSlot[]>([]);

  // 生成済みのルート結果（候補一覧・地図描画・選択状態）だけをリセットする。経由地・
  // 目的地のピンは対象外（別々の「クリア」操作として使い分けられるようにする）。研究
  // モード中の生成はexperimentSlotsへも記録され地図へ重ね描きされる
  // （EXPERIMENT_SLOT_COLORSの先頭）ため、「ルートをクリア」を押した見た目
  // どおり地図が空になるよう、実験スロットも同時にクリアする（比較履歴を残すよりも
  // 「クリアしたら地図が本当に空になる」という一般的な期待を優先）。
  const handleRoutesClear = useCallback(() => {
    setRoutes([]);
    setSelectedRouteId(null);
    setComparisonTabActive(false);
    setGeneratedConditions(null);
    setExperimentSlots([]);
    setSelectedRouteSegment(null);
  }, []);

  // 「ルートを作る」セクションの開閉（デスクトップのみ。主機能のためデフォルト開）。
  // モバイルはBottomSheetの開閉自体がこれに相当するため参照しない。
  const [generateOpen, setGenerateOpen] = useStoredBooleanState(GENERATE_OPEN_STORAGE_KEY, true);
  const [outcomeOpen, setOutcomeOpen] = useStoredBooleanState(OUTCOME_OPEN_STORAGE_KEY, true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  // モバイルで開いている下部シート（排他表示、またはどれも閉じたnull＝地図全面表示）。
  // デスクトップでは使わない。
  const [mobileSheet, setMobileSheet] = useState<MobileSheet>(null);
  // ドラッグ中は毎フレームstateだけ更新し（見た目の即時反映）、保存はドラッグ確定時の
  // commitMobileSheetHeightのみで行う（毎フレーム書き込みを避けるためautoSave: false）。
  const [mobileSheetHeightVh, setMobileSheetHeightVh, commitMobileSheetHeight] = useStoredState(
    MOBILE_SHEET_HEIGHT_STORAGE_KEY,
    DEFAULT_SHEET_HEIGHT_VH,
    {
      autoSave: false,
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
  // 利用者が自分でシートの高さを決めたか。決めた後は中身に合わせた自動調整をやめ、その
  // 高さを使い続ける（保存値があること自体が「決めた」の証跡——自動調整はonHeightChange
  // までで保存しないため、保存値はドラッグ/キー操作の確定でしか生まれない）。
  const [sheetHeightChosen, setSheetHeightChosen] = useState(false);
  useIsomorphicLayoutEffect(() => {
    try {
      setSheetHeightChosen(window.localStorage.getItem(MOBILE_SHEET_HEIGHT_STORAGE_KEY) != null);
    } catch {
      // localStorageを使えない環境では「決めていない」（自動調整のまま）で構わない。
    }
  }, []);

  // DebugPanel（デバッグモードON/OFFの設定）・SystemStatusPanel・BackendStatus
  // （バックエンド集計情報、地図に依存しない）は/adminにあるが、DebugConsole（地図の
  // 表示イベント・API呼び出しのライブログ）は地図インスタンスに紐づく情報のためこの
  // ページに置く（「/admin=設定・集計」「/=地図を操作しながら見るライブログ」という
  // 役割分担）。デバッグモードのON/OFF自体（useDebugEnabled、researchMode.tsと同型の
  // localStorage共有フラグ）は/adminのDebugPanelで切り替える。
  const debugEnabled = useDebugEnabled();
  const [debugConsoleOpen, setDebugConsoleOpen] = useState(false);
  const researchEnabled = useResearchEnabled();
  // RouteSettingsPanelのroute_preferenceキー整合自己修復はそのパネルがマウントされた
  // ときにしか走らない。モバイルでは生成ボタンがヘッダーへ分離されているため「ルート
  // 設定」タブを一度も開かずに生成できてしまい、稀にキー不整合のまま送信して422になり
  // うる。ここでもカタログ（axisCatalog、
  // コンポーネント先頭で取得済み）を使い、生成リクエスト組み立て時（handleGenerate）に
  // 同じ整合チェックを適用する（syncRoutePreferenceKeys、RouteSettingsPanel.tsxと共有）。
  // routePreference state自体は書き換えない（送信直前の値だけを補正する、常時同期化は
  // スコープ外）。

  const selectedCandidate = routes.find((r) => r.id === selectedRouteId) ?? null;

  // 区間の乗り換えの導出値。edge_idsの集合演算だけで求まる
  // （軸の計算式は持たない。構造仕様1）。**区間を主語に、その区間の代替を候補横断で並べる**。
  // 編集対象は`routes`から引く（`editingRouteId`を単独で見ない）。候補が入れ替わった・
  // 消えたときに編集モードだけが生き残ると、地図の地点編集・候補選択が無言で無効のまま
  // 戻せなくなる。
  const editingRoute = routes.find((route) => route.id === editingRouteId) ?? null;
  // 以下はどれもMapViewへ渡る配列・オブジェクトを組み立てる。毎レンダー作り直すと参照だけが
  // 変わり、地図側の描画effectが天候フェッチ・パン確定などあらゆる再レンダーで走る
  // （30km級では候補1本あたり数千件のEdge idを毎回舐め直すことになる）。
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
  // いまの組み合わせ（元＋適用済みの乗り換え）。次に選べる区間も、評価へ送るEdge列もこれを
  // 見る——乗り換えた先の道の上にある分かれ道へ、そのまま進めるようにするため（T843）。
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
            // 座標まで渡すと、2本が交差・接触する地点でも区間を割れる（Edge idの一致だけでは
            // 1本の長い区間になり、他候補1本との丸ごと入れ替えにしかならない）。
            { baseShape: splicedShape, minSplitLengthKm: minStretchKm },
          )
        : [],
    [splicedShape, candidateShapes, editingRouteId, minStretchKm],
  );
  // 地図へ渡す帯は相手側の形。まだ選んでいない道を破線で示す（適用済みの道はいまの経路の
  // 一部になるため、帯としては出ない）。indexは「グループの位置と選択肢の位置」を1つの数に
  // したもの（地図のタップから引き戻す）。
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
          return [{ index: spliceFeatureIndex(groupIndex, optionIndex), taken: false, coordinates }];
        }),
      ),
    [spliceGroups, routes],
  );

  // 適用した順で識別する。同じ位置でも積み上げた経緯が違えば別の経路になるため順番を含める。
  const spliceChoiceKey = appliedAlternatives
    .map((item, index) => `${index}:${item.candidateId}:${item.stretch.start}-${item.stretch.end}`)
    .join("|");
  const splicePreview = splice?.previews[spliceChoiceKey] ?? null;
  // 地図の帯をタップしたら、その道へ乗り換える。次に選べる区間はこの結果から求め直すため、
  // 乗り換えた先の道の上にある分かれ道がそのまま次の帯になる。
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

  // 地図上の▼ページ送り判定（MapOverlayControls.tsx: usePagedOverflow）が、兄弟要素として
  // 重なる気象タイムラインパネル（下記.bottomControlRow）の占有高さを知らず、パネル表示中に
  // 一番下のアイコンチップがパネルの裏へ隠れてしまう不具合への対応。共通の祖先（.mapPane）へ
  // 実測高さをCSS変数として反映し、MapOverlayControls.module.cssの.wrapper側で読む。
  // 地図へピンを置けるのは「ルート設定」を見ている間だけ。ルート結果を見ているときは
  // 候補線を選ぼうとして少し外すたびに経由地が増えてしまう——生成に関わる操作は
  // 「ルート生成」ボタンがある場所でだけ受け付ける。モバイルはシートの排他表示、
  // デスクトップは区分の開閉が「見ているか」にあたる。
  // 「ルート設定」区分のタブ（条件/重み/除外）。タブ列は見出し行、中身は本文と離れた
  // 場所に描くため、両方を囲むTabs.Rootと同じ場所（page.tsx）で選択状態を持つ。
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("generate");

  const routeSettingsActive = isMobile ? mobileSheet === "routeSettings" : generateOpen;
  // 地点の行が見えている場所でだけピンを置ける。「ルート結果」を見ている間や、「重み」
  // 「除外」タブを開いている間は、武装していても地図のタップはピンにしない（T781と同じ理屈で、
  // 地図を触った副作用で地点が変わらないようにする）。
  const routeOutcomeActive = isMobile ? mobileSheet === "routeOutcome" : outcomeOpen;
  // 地図でできることは、いま見ているパネルが持つ操作だけにする。
  // 「ルート設定」の条件タブ＝地点を置く・つかんで動かす・消す。「ルート結果」＝候補の
  // 切り替えと区間詳細。「ルート編集」＝乗り換え先の選択だけ（元は固定）。
  const pointEditingEnabled = routeSettingsActive && settingsTab === "generate" && editingRoute === null;
  const routeInspectionEnabled = routeOutcomeActive && editingRoute === null;
  const pinPlacementArmedRole = routeMode === "destination" && pointEditingEnabled ? armedPinRole : null;

  const handleRouteSelectFromMap = useCallback(
    (routeId: string) => {
      // 候補の切り替えは「ルート結果」を見ている間だけ。編集中に地図で他候補へ移ると、
      // パネルが示す元と地図で強調されるルートが食い違い、何を編集しているのか読めなくなる。
      if (!routeInspectionEnabled) return;
      setSelectedRouteSegment(null);
      setSelectedRouteId(routeId);
    },
    [routeInspectionEnabled],
  );

  const mapPaneRef = useRef<HTMLDivElement>(null);
  const bottomControlRowRef = useRef<HTMLDivElement>(null);
  useElementHeightCssVar(bottomControlRowRef, mapPaneRef, "--bottom-control-row-height");

  // 地図キャンバスはモバイルの下部タブバー・ボトムシートの下にも描画されている
  // （page.module.css .mobileTabBar参照）ため、ルート生成直後のフィットが既定の余白だけ
  // だと、ルート全体がシートの裏へ収まって1本も見えない。覆われている高さを、地図がフィットする
  // 瞬間に測って渡す（地図はその瞬間の値しか使わない）。タブバーの高さはCSS
  // （--mobile-tabbar-height）が正のため実測し、シートは高さ自体をvhで持っている（BottomSheet）
  // ためビューポート高から換算する。
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

  // モバイルタブバーのボタン操作。同じタブを再タップしたら閉じる（トグル）。
  const handleMobileTabClick = useCallback(
    (sheet: Exclude<MobileSheet, null>) => {
      setMobileSheet((prev) => (prev === sheet ? null : sheet));
      // 「ルート結果」タブを開いたら、新着結果の合図は役目を終える。
      if (sheet === "routeOutcome") setHasUnseenResults(false);
    },
    [setMobileSheet],
  );

  // 下部シートの高さ変更。ドラッグ中/キー操作中は見た目の即時反映のみ（onHeightChange）、
  // 確定時のみ保存する（onHeightCommit。ドラッグ中の毎フレーム書き込みを避けるため、
  // useStoredStateのautoSave: falseとcommitMobileSheetHeightで分離している）。
  const handleMobileSheetHeightChange = useCallback(
    (vh: number) => {
      setMobileSheetHeightVh(vh);
    },
    [setMobileSheetHeightVh],
  );

  const handleMobileSheetHeightCommit = useCallback(
    (vh: number) => {
      setSheetHeightChosen(true);
      commitMobileSheetHeight(vh);
    },
    [commitMobileSheetHeight],
  );

  // 今日の見通し（TodayOutlook向け、気象庁MSM予報）・最寄りアメダス実測値（WeatherPanel＝
  // 常設ヘッダー向け）・警告バッジ3種（JMA警報・注意報／WBGT／河川氾濫予報）のフェッチ・
  // 状態管理（useWeatherConditionsが持つ。weather[MSM予報]とamedas[アメダス実測]は
  // 独立フェッチ）。locationReadyになるまで待ち、その後はlocationが変わるたびに
  // 再フェッチする。
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

  // 現在のフォーム値から生成リクエストの入力一式を組み立てる。生成時（handleGenerate）と
  // dirty判定の両方がこの1つの関数を通るため、送る値を足したときに比較側へ足し忘れる形の
  // 欠陥が起きない（lib/generationRequest.ts参照）。
  // `destinationOverride`はbackendが補正した目的地を渡すためのもの。補正後のキーを作るとき
  // フィールドを個別に差し替えると、そのフィールドから導かれる値（distanceKm）が補正前の
  // ままになる——同じ組み立てをここ1箇所に通すことで、その取りこぼしが起きない。
  const buildCurrentGenerationInput = useCallback(
    (distanceKm: number, destinationOverride?: Coordinates): GenerationInput => {
      const effectiveDestination = destinationOverride ?? destination;
      const destinationModePoints =
        routeMode === "destination" ? [...waypoints, ...(effectiveDestination ? [effectiveDestination] : [])] : [];
      return {
        origin: location,
        // 目的地モードでは距離をRouteForm（distanceKm=0固定）から受け取らず、地図上の
        // 経由地・目的地から自動算出する。distance_kmはbackendのbbox見積り半径のほか、
        // 「起点から近すぎる=distance_km未満」バリデーション（routes.py:
        // _check_waypoints_within_range）の基準にもなるため、実際に指定した点の最遠距離を
        // 必ず上回る値にする（+1kmの余裕、MAX_DISTANCE_KMで頭打ち）。
        distanceKm:
          routeMode === "destination" && destinationModePoints.length > 0
            ? Math.min(
                MAX_DISTANCE_KM,
                // reduceの初期値0で畳む（`Math.max(...[])`は-Infinityを返し、
                // distance_kmがnullとしてbackendへ渡って422になる）。
                Math.ceil(destinationModePoints.reduce((max, p) => Math.max(max, haversineKm(location, p)), 0)) + 1,
              )
            : distanceKm,
        distanceToleranceKm: routeGenerateConfig.default_distance_tolerance_km,
        maxRoutes: Number(maxRoutesInput),
        assumedSpeedKmh,
        startTime: departure.at,
        startTimePinned: departure.pinned,
        hardFilters,
        // 軸カタログ未取得のまま軸idを送ると、backendは存在しない軸idを黙って無視する
        // （road_graph_engine.py: AXIS_DEFINITIONS.get(lens_axis_id)、422にはならない）。
        // route_preferenceと同じく、カタログが未確定の間は送らない——選んだ軸で塗られない
        // 事実が手掛かり無しで起きるのを避ける（失敗自体はRouteSettingsPanelが表示する）。
        lensAxisId:
          axisCatalog.loaded && mapView.lens !== LENS_NONE_ID && mapView.lens !== LENS_DIFFICULTY_ID
            ? mapView.lens
            : null,
        routePreference: routePreferenceToSend(
          routePreference,
          { loaded: axisCatalog.loaded, defaultWeights: axisCatalog.defaultWeights },
          weightOverrideEnabled,
        ),
        // 周回モードでは経由地・目的地の値が残っていても送らない（モード切り替え自体は
        // 値を消さないため、地図上にピンが残っていても周回モード中は無視する）。
        waypoints: routeMode === "destination" ? waypoints : [],
        destination: routeMode === "destination" ? effectiveDestination : null,
        maxRoutesRelevant: routeMode === "loop" || waypoints.length === 0,
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

  // 表示中の候補の生成条件と現在のフォーム値がずれているか（生成条件系は「生成ボタンで
  // 反映」のため、編集しただけでは何も起きない。それをヒントとして可視化する）
  const conditionsDirty =
    generatedConditions != null &&
    routes.length > 0 &&
    generationConditionsKey(buildCurrentGenerationInput(Number(distanceInput))) !== generatedConditions.key;

  // 選んだ区間を相手の道へ差し替えた経路を、backendで評価し直して候補一覧へ加える。
  // frontendは経路の組み立てだけを行い、評価はbackendが
  // 既存候補と同じ経路で行う（構造仕様1・10）。
  // 選んだ組み合わせをbackendで評価する。差分の表示と「作る」で同じものを使い、評価済みなら
  // 投げ直さない。
  async function evaluateSplicedRoute(): Promise<RouteCandidate | null> {
    if (!editingRoute || appliedAlternatives.length === 0 || !splicedShape) return null;
    const cached = splice?.previews[spliceChoiceKey];
    if (cached) return cached;
    // 表示中の候補を作った条件をそのまま使う。いまのフォーム値を使うと、生成後に重みを
    // 変えてから合成したときに、その1本だけ別条件で評価された候補が同じ並びへ入る。
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

  // 作る前に「この組み合わせにすると何がどう変わるか」を見る。評価はbackendでしか出せない
  // （Edgeコストは探索と表示で同じ値を共有する、構造仕様10）ため、押したときだけ投げる。
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
    // 連打で2本入るのを防ぐ。disabledはstateの反映（再レンダー）を待つため、その手前で
    // 2回目のタップが入ると同じ組み合わせが2本一覧へ並ぶ。
    if (applyingRef.current) return;
    if (!editingRoute || appliedAlternatives.length === 0) return;
    // 表示中の候補を作った条件をそのまま使う。いまのフォーム値を使うと、生成後に重みを
    // 変えてから合成したときに、その1本だけ別条件で評価された候補が同じ並びへ入る。
    // **前提の確認は連打防止フラグを立てる前に済ませる**。フラグを立ててから抜ける経路が
    // 1つでもあると、`finally`を通らないままフラグが立ちっぱなしになり、以後この操作が
    // 二度と効かなくなる（判断原則16）。
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
      // 区間を全部その候補の道へ乗り換えると、出来上がりは既存の候補そのものになる。
      // 同じ道を2本並べても選べるものは増えず、利用者からは重複にしか見えないため、
      // 既にある候補を選ぶだけにする。
      const sameRoute = routes.find((route) => route.edge_ids.join(",") === spliced.edge_ids.join(","));
      // 素の結果と本質的に区別しないため、生成候補と同じ並び順の規約へ乗せる
      // （lib/routeSplice.ts: insertByDifficulty）。見分けはタブの名前で付ける。
      // max_routesによる切り詰めはしない——上限は「生成が何本探すか」の指定で、
      // 利用者が作った組み合わせを押し出す理由が無い。
      const unique = { ...spliced, id: `${SPLICED_ROUTE_ID_PREFIX}-${routes.length}` };
      if (!sameRoute) setRoutes(insertByDifficulty(routes, unique));
      setSelectedRouteId(sameRoute ? sameRoute.id : unique.id);
      setSelectedRouteSegment(null);
      // 同じ場所が結果の一覧へ戻り、作ったルートが選ばれた状態で並ぶ。
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
      // 送るpayloadとdirty判定の比較キーを同じ入力から導出する（lib/generationRequest.ts）。
      // 候補数はステッパー（‹/›）操作のみで変更でき、1〜MAX_ROUTES範囲の整数文字列以外には
      // なり得ないため、buildCurrentGenerationInput側でそのままNumber化して使う。
      const generationInput = buildCurrentGenerationInput(distanceKm);
      const {
        routes: candidates,
        conditions,
        noCandidatesReason,
      } = await generateRoutes(buildGenerateRequest(generationInput), (progress) =>
        setGeneration({ status: "running", progress }),
      );
      // backendが目的地をアクセス可能な最寄り地点へ補正した場合、地図上のピンも実際に
      // 使われた地点へ合わせる（そのままだと地図のピン位置と生成されたルートの終点が
      // ずれて見える）。
      if (conditions.corrected_destination) {
        setDestination(conditions.corrected_destination);
      }
      setRoutes(candidates);
      setSelectedRouteId(candidates[0]?.id ?? null);
      // 比較タブを開いたまま生成したときは、新しい候補へ戻す——押した操作の結果が
      // 見えないまま前回までの比較表が残ると、生成が効かなかったように見える。
      setComparisonTabActive(false);
      // 候補集合が入れ替わると、区間の位置も選んだ道も意味を失う。
      setSplice(null);
      // 新しい候補集合に対して、それより前にクリックしていた区間の選択を引き継がない
      // （同じedge_idが新しい生成結果に存在するとは限らず、地図上のマーカーも意味を
      // 失うため）。
      setSelectedRouteSegment(null);
      // 新しい候補が用意できたことを「ルート結果」タブへ知らせる（モバイルのみ表示に
      // 使うが、状態自体はプラットフォーム非依存で立てる）。
      setHasUnseenResults(candidates.length > 0);
      // dirty判定の基準は「いま表示している候補を作った条件」。エラー時は既存候補が
      // 残るため更新しない（tryの成功パスでのみ更新する）
      // 補正があった場合は補正後の地点で入力を組み直す（地図上のピンも補正後の地点へ
      // 動かしているため、conditionsDirtyが直後に誤ってtrueにならないように揃える）。
      // 組み直すのは、目的地から導かれるdistance_kmも一緒に揃える必要があるため。
      const generatedInput = conditions.corrected_destination
        ? buildCurrentGenerationInput(distanceKm, conditions.corrected_destination)
        : generationInput;
      setGeneratedConditions({
        key: generationConditionsKey(generatedInput),
        destinationCorrected: Boolean(conditions.corrected_destination),
        // 実際に探索された地点を持つ。
        input: generatedInput,
        routePreference: conditions.route_preference,
      });
      if (candidates.length === 0) {
        // バックエンドが原因を特定できた場合はそれを表示する（routeApi.ts:
        // generateRoutes参照）。特定できない場合のみ汎用文言。
        message = noCandidatesReason ?? "条件に合うルート候補が見つかりませんでした。距離を変えて試してください。";
        notifyRouteOutcome();
      } else if (researchEnabled) {
        // 実験スロットへの記録は研究モード中の生成のみ（研究用機能を一般ユーザーの
        // 通常操作から隠す方針、§14。ログ表示のデバッグモードとは独立）。
        // overall_difficulty最小（=candidates[0]）を比較代表候補として
        // 固定し、以降の候補選び直しでは変えない（スロット=生成結果のスナップショット）。
        setExperimentSlots((prev) => {
          const next: ExperimentSlot = {
            id: `slot-${conditions.generated_at}-${Math.random().toString(36).slice(2, 8)}`,
            color: EXPERIMENT_SLOT_COLORS[0],
            conditions,
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
      message = error instanceof Error ? error.message : "不明なエラーが発生しました";
      // generateRoutes（routeApi.ts: postJson）自体の失敗は既にそちらでdebugLog記録済みだが、
      // ここに来る他の例外（候補構築中の想定外エラー等）も含め、ルート生成ハンドラの失敗として
      // ここでも記録する（多層防御）。
      debugLog("api:route", "ルート生成ハンドラで例外", { error: message }, "error");
      notifyRouteOutcome();
    } finally {
      setGeneration({ status: "idle", message });
    }
  }

  // 生成の結果（候補・失敗のいずれも）は「ルート結果」欄でしか見えないため、そこへ
  // 目を向けさせる。デスクトップは畳まれていると本文ごと見えないので開き、モバイルは
  // タブのドットで知らせる（シートは排他表示のため勝手に開かない）。
  const notifyRouteOutcome = useCallback(() => {
    setOutcomeOpen(true);
    setHasUnseenResults(true);
  }, [setOutcomeOpen]);

  // 入力の検証エラー（useRouteFormSubmit）も同じ扱いにする——「ルート生成」を押した
  // 結果であることは変わらず、出し先も同じ（renderRouteOutcomeEmptyState）。
  useEffect(() => {
    if (routeFormSubmit.error) notifyRouteOutcome();
  }, [routeFormSubmit.error, notifyRouteOutcome]);

  // 「ルート生成」ボタン（page.tsx「ルート設定」見出し行）の文言。queued（同時実行数
  // 上限で順番待ち）とrunning（経過時間つき）を区別する。nullの間は
  // 既定文言（「生成中...」）に委ねる。
  const generationProgress = generation.status === "running" ? generation.progress : null;
  const generationProgressLabel =
    generationProgress?.status === "queued"
      ? "順番待ち..."
      : generationProgress?.status === "running"
        ? `生成中...(${Math.round(generationProgress.elapsedMs / 1000)}秒経過)`
        : undefined;

  // 「ルート設定」見出し行の右側アクション（renderRouteResultHeaderActionsと同じ場所、
  // デスクトップはDisclosureのtrailing・モバイルはBottomSheetのheaderAction）。
  // 「ルート生成」ボタンをタブの外に置くことで、重みづけタブを見ている間もタブを
  // 切り替えずに押せるようにする。
  // 「ルート設定」区分のタブ列。タブ専用の行を持たず見出し行へ同居させる（本文の縦を
  // 空ける）。中身を切り替えるタブと「ルート生成」は役割が違うため、タブは見出しの側＝左、
  // ボタンは右端と、行の中でも離して置く。
  function renderSettingsTabs() {
    return (
      <Tabs.List className={styles.settingsTabList} aria-label="ルート設定">
        <Tabs.Trigger className={styles.settingsTabTrigger} value="generate">
          条件
        </Tabs.Trigger>
        <Tabs.Trigger className={styles.settingsTabTrigger} value="weights">
          重み
        </Tabs.Trigger>
        <Tabs.Trigger className={styles.settingsTabTrigger} value="exclusions">
          除外
        </Tabs.Trigger>
      </Tabs.List>
    );
  }

  function renderRouteSectionHeaderActions() {
    return (
      <div className={styles.routeSectionHeaderActions}>
        {/* 「生成条件が変更されています」は結果欄の先頭にも出るが、条件を変えている本人は
            設定側を見ている。押すべきボタンの隣でも同じことを知らせる。 */}
        {conditionsDirty && (
          <span
            className={styles.dirtyDot}
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

  // 「ルート設定」区分の中身（天候は常設ヘッダにある）。
  // デスクトップの`Disclosure`（summary="ルート設定"）・モバイルの`BottomSheet`
  // （title="ルート設定"）の両方から呼ぶ。見出しはどちらも呼び出し元コンテナが持つため、
  // このセクション自身は見出しを持たない。
  function renderRouteSectionBody() {
    return (
      <>
        {/* 生成に関するフィードバック（検証エラー・APIエラー・候補0件・生成中）はここには
            出さない。「ルート生成」ボタンは見出し行にあり本文を畳んだままでも押せるため、
            押した結果を本文の中に出すと操作している場所から見えない。出し先は
            renderRouteOutcomeEmptyState（「ルート結果」欄）に一本化する。 */}
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
          weightsPanel={renderRouteSettingsSectionBody()}
          exclusionsPanel={<HardFilterPanel hardFilters={hardFilters} onHardFiltersChange={setHardFilters} />}
        />
      </>
    );
  }

  // 「ルート結果」欄に候補が無いときの中身。生成前・生成中・失敗（検証エラー・APIエラー・
  // 候補0件）を出し分ける単一の置き場で、デスクトップ（Disclosure）・モバイル（BottomSheet）の
  // 両方から呼ぶ。候補0件で生成前の案内文へ戻ると「押したのに何も起きていない」ように見える。
  function renderRouteOutcomeEmptyState() {
    if (loading) {
      return <p className={styles.emptyHint}>{generationProgressLabel ?? "生成中..."}</p>;
    }
    const failure = routeFormSubmit.error ?? (generation.status === "idle" ? generation.message : null);
    if (failure) {
      return <ErrorText>{failure}</ErrorText>;
    }
    return <p className={styles.emptyHint}>「ルート生成」を押すと候補がここに並びます</p>;
  }

  // 一般ユーザー向けルート設定。0次(除外)・軸選択・重みを生成前に調整できる、常時表示の
  // メイン導線（route_preference・weightOverrideEnabledの
  // 状態はpage.tsx冒頭のstate宣言・handleGenerateのコメント参照）。renderRouteSectionBody
  // からのみ呼ばれ、見出しは持たない（呼び出し元コンテナが持つ、上記コメント参照）。
  function renderRouteSettingsSectionBody() {
    return (
      <RouteSettingsPanel
        routePreference={routePreference}
        onRoutePreferenceChange={setRoutePreference}
        overrideEnabled={weightOverrideEnabled}
        onOverrideEnabledChange={setWeightOverrideEnabled}
      />
    );
  }

  // 「ルート結果」見出し脇の右側アクション群（保存・GPX出力・ルートをクリア）。
  // デスクトップ（見出し行）・モバイル（BottomSheetのheaderAction）の両方から同じ中身を
  // 呼ぶ。routes.length===0の間はどちらの呼び出し元も描画自体をスキップする
  // （デスクトップはrenderRouteOutcomeSectionBody自体がnullを返す、モバイルは呼び出し側で
  // routes.lengthを見てheaderActionをundefinedにする）ため、ここでは呼ばれた時点で必ず
  // routes.length>0という前提でよい。
  function renderRouteResultHeaderActions() {
    return (
      <>
        {/* 編集（区間の乗り換え）の入口。選択中の候補に対する操作のため、GPX出力と同じ
            アイコン列へ置く。乗り換えできない生成（周回・候補1件）では出さない——押しても
            何もできない入口を残さない。編集中は戻る導線がパネル側にあるため重ねない。 */}
        {canSpliceDisplayedRoute() && editingRoute === null && (
          <button
            type="button"
            className={styles.outcomeHeaderIcon}
            onClick={() => {
              if (!selectedCandidate) return;
              setSplice({ routeId: selectedCandidate.id, applied: [], previews: {}, task: SPLICE_IDLE });
              // 区間詳細（赤ピン）の置き場は候補タブの中身で、編集中はそこが編集面へ
              // 置き換わる。選択を残すと地図にピンだけが残り、消す導線も無くなる。
              setSelectedRouteSegment(null);
            }}
            title="このルートを編集（区間の乗り換え）"
            aria-label="このルートを編集"
          >
            <RouteSpliceIcon size={18} />
          </button>
        )}
        {/* 選択中候補のgeometry（区間分割前の連続したLineString）をGPXへ書き出す。
            selectedCandidateがnullの間は押せない（比較タブ表示中等）。 */}
        <button
          type="button"
          className={styles.outcomeHeaderIcon}
          disabled={!selectedCandidate}
          onClick={() => selectedCandidate && downloadGpx(selectedCandidate)}
          title="GPX出力"
          aria-label="GPX出力"
        >
          <DownloadIcon size={18} />
        </button>
        {/* 生成済みの候補一覧・地図描画・選択状態だけをリセットする（経由地・目的地のピンは
            対象外、別々のクリア操作として使い分ける）。押した瞬間に実行する即実行アクション。
            保存・GPX出力と並ぶアイコンボタンにし、他の2つと見た目を揃える。 */}
        <button
          type="button"
          className={styles.outcomeHeaderIcon}
          onClick={handleRoutesClear}
          title="ルートをクリア"
          aria-label="ルートをクリア"
        >
          <ClearRoutesIcon size={18} />
        </button>
      </>
    );
  }

  // 生成結果に関する表示（設定変更の警告・候補ごとの内訳・比較表・色分け設定、ルート設定は
  // 含まない）。モバイルの「ルート結果」タブ、デスクトップの「ルートを作る」ブロック後半から
  // 呼ぶ。生成前はほぼ何も出さず、生成後は候補ごとの内訳・比較表をタブで区切って1画面に
  // 収める。
  //
  // 「ルート結果」パネルの外側タブは、候補ごとのタブ＋「比較」タブという1段のフラットな
  // タブ列。候補の切り替えとその候補の内訳表示（RouteAxisProfile）を、このタブ列自体が
  // 担う——RouteAxisProfileはタブの中身（Tabs.Content）としてのみ現れる。
  //
  // この関数は見出しを描画しない（中身だけを返す）。見出し「ルート結果」はデスクトップが
  // Disclosureのsummary、モバイルがBottomSheetのtitleとして持つ。ヘッダの操作アイコン
  // （保存・GPX出力・ルートをクリア）も同様に、renderRouteResultHeaderActions()を
  // デスクトップはDisclosureのtrailing、モバイルはBottomSheetのheaderActionへ渡す。
  // 総合難易度の説明はRouteAxisProfile側（総合難易度の表示の隣）にあり、
  // 本ヘッダは操作アイコンのみを持つ。
  function renderRouteOutcomeSectionBody() {
    // 編集中は同じ場所が編集面になる（「ルート編集」という別の置き場を持たない）。
    if (editingRoute) return renderRouteEditSectionBody();
    if (routes.length === 0) return null;

    const showComparisonTab = researchEnabled;
    const outerTabValue = comparisonTabActive ? "comparison" : (selectedRouteId ?? routes[0].id);
    // 基準線（好みの重みを0にしたときの経路）の所要時間秒（目的地モードのみ持つ。
    // 周回・経由地ルートはnull）。
    const fastestSeconds = fastestDurationSeconds(routes);
    const fastestRouteIdInList = fastestRouteId(routes);
    // 難易度の帯の高さ1.0とする距離。帯の長さは総合難易度なので、高さへ距離を与えると
    // 塗られた面積が負荷（difficulty_load）になる（lib/difficultyLoadBar.ts）。一覧の行と
    // 候補の中身（RouteAxisProfile）で同じ基準を使う——同じ見た目の帯が場所によって別の
    // 尺度になると、行と中身で面積が食い違う。
    const loadBarBaselineKm = baselineDistanceKm(routes);
    // RouteAxisProfileへは公開軸すべて（axisCatalog.axes）をそのまま渡し、絞り込みは行わない。
    // routeWeightsは重み<=0の軸を「未使用」バッジ付きで表示する判定にのみ使う（生成時点の重み
    // ＝generatedRoutePreference、未生成時のみライブなroutePreferenceへフォールバック）。
    // 全候補で共通のため、候補ごとのTabs.Contentループの外で1回だけ計算する。
    const routeWeights = generatedRoutePreference ?? routePreference;

    return (
      <>
        {conditionsDirty && <p className={styles.dirtyHint}>生成条件が変更されています</p>}
        {/* 指定した目的地が自転車で行ける道路につながっていなかったため、backendが
            最寄りのアクセス可能な地点へ補正して生成した場合の案内（地図上のピンも
            補正後の地点へ動かす、handleGenerate参照）。 */}
        {generatedConditions?.destinationCorrected && (
          <p className={styles.dirtyHint}>
            指定した地点は自転車で行けない場所だったため、近くのアクセス可能な地点へ補正しました。
          </p>
        )}
        <Tabs.Root
          className={styles.outcomeTabs}
          // 候補は横並びのタブだと幅に収まらず（8件で列の必要幅が表示幅の3倍近くになる）、
          // 溢れた候補が存在ごと見えなくなる。1行1候補の縦並びにして、行の中へ距離と
          // 総合難易度を並べる——横幅の制約から外れるぶん、タブを開かずに見比べられる。
          orientation="vertical"
          value={outerTabValue}
          onValueChange={(value) => {
            // 候補タブ・比較タブいずれへ切り替えても、他候補でクリックしていた区間の
            // 選択は引き継がない（別候補のedge_idを指したまま地図マーカー・内訳が残ると
            // 実態と食い違いを起こすため）。
            setSelectedRouteSegment(null);
            if (value === "comparison") {
              setComparisonTabActive(true);
            } else {
              setComparisonTabActive(false);
              setSelectedRouteId(value);
            }
          }}
        >
          <div className={styles.outcomeTabBar}>
            <Tabs.List className={styles.outcomeTabList} aria-label="ルート結果">
              {routes.map((route, index) => (
                <Tabs.Trigger key={route.id} className={styles.outcomeTabTrigger} value={route.id}>
                  {/* タブは候補を見分ける表記（順位番号・距離）と、開かずに見比べるための
                      総合難易度を持つ。
                      並び順（overall_difficulty昇順）に沿った1始まりの順位番号を先頭に
                      付け、方位が同じ候補どうしも見分けられるようにする（周回生成は軸重み
                      駆動のフロンティア方式のため、同じ方位ラベルの候補が複数並びうる。
                      direction_labelは折返し地点の方位から表示専用に導出するだけで、候補
                      選定の基準ではない）。経由地ルート(route-waypoints)は候補が常に1件で
                      「方位」という概念が無いため、direction_label（固定文言、
                      route_generator.py参照）をそのまま表示し順位番号も付けない。目的地
                      ルート(route-destination-00形式、前方一致)は経由地を伴わなければ
                      via-node方式で複数件になりうる——方位という概念は無いため「方向」は
                      付けないが、複数件を見分けられるよう順位番号は付ける。 */}
                  <span className={styles.outcomeTabMain}>
                    {NON_DIRECTIONAL_ROUTE_IDS.has(route.id) ? route.direction_label : `${index + 1}`}{" "}
                    {route.distance_km.toFixed(1)}km
                    {/* 区間を乗り換えて作った候補。並び順は生成候補と同じ規約に乗せ
                        （insertByDifficulty）、見分けは名前で付ける。 */}
                    {isSplicedRoute(route) && <span className={styles.outcomeTabExtra}>合成</span>}
                    {/* 基準線（一覧の中で所要時間が最小の候補）と、そこから何分余計に
                        かかるか。軸設定に沿ったルートを走る対価であり、候補を見比べるこの
                        場所に無いと、比較のたびにタブを開き直すことになる。同じ列へ時間の
                        最上級と距離の最上級を並べると何と比べているのか読めなくなるため、
                        ここは時間に絞る。 */}
                    {route.id === fastestRouteIdInList ? (
                      <span className={styles.outcomeTabExtra}>最速</span>
                    ) : (
                      extraDurationLabel(route, fastestSeconds) && (
                        <span className={styles.outcomeTabExtra}>{extraDurationLabel(route, fastestSeconds)}</span>
                      )
                    )}
                  </span>
                  {/* 総合難易度。タブを開かずに候補どうしを見比べられるよう、数値と長さの
                      両方で出す（数値だけだと並びの中の位置が読み取りにくい）。 */}
                  {/* 算出できなかった候補（overall_difficultyがnull）は、長さを描かず
                      「—」だけ出す——0と欠損を同じ見た目にしない。 */}
                  <span className={styles.outcomeTabScore}>
                    <span
                      className={styles.outcomeTabScoreTrack}
                      style={
                        {
                          "--load-bar-height-ratio": String(loadBarHeightRatio(route.distance_km, loadBarBaselineKm)),
                        } as React.CSSProperties & { "--load-bar-height-ratio"?: string }
                      }
                    >
                      {route.overall_difficulty !== null && (
                        <span className={styles.outcomeTabScoreBar} style={{ width: `${route.overall_difficulty}%` }} />
                      )}
                    </span>
                    <span className={styles.outcomeTabScoreValue}>
                      {route.overall_difficulty === null ? "—" : Math.round(route.overall_difficulty)}
                    </span>
                  </span>
                </Tabs.Trigger>
              ))}
              {/* 比較タブ: researchEnabledの間は常に出す。ComparisonPanel自身が実験
                  スロット2件未満の間は中身を持たない自己ガードを持つ（ComparisonPanel.tsx
                  参照）ため、ここでスロット件数を重複判定しない。 */}
              {showComparisonTab && (
                <Tabs.Trigger className={styles.outcomeTabTrigger} value="comparison">
                  比較
                </Tabs.Trigger>
              )}
            </Tabs.List>
          </div>
          {/* 右カラム。選ばれている候補の中身だけがここに出る（Radixが他を[hidden]にする）。 */}
          <div className={styles.outcomeTabPanes}>
            {routes.map((route) => (
              <Tabs.Content key={route.id} className={styles.outcomeTabPanel} value={route.id}>
                {/* 区間がクリックされている間（selectedRouteSegment）は、ルート全体の
                  内訳の代わりにその区間の地点・到達予想時刻＋軸別内訳（AxisContributionBar、
                  ルート全体の内訳と同じ表示部品）を表示する。地図側の詳細区間（sceneの役割
                  `detailLine`/`detailHit`）は選択中候補の区間しか描かない（applyToMap.ts）
                  ため、区間クリックは常に現在アクティブなこのタブのルートに対して起きる
                  （他候補のタブが誤って区間詳細を出すことは無い）。 */}
                {selectedRouteSegment ? (
                  <div className={styles.selectedSegmentPanel}>
                    <div className={styles.selectedSegmentHeader}>
                      <span className={styles.selectedSegmentTitle}>
                        {selectedRouteSegment.segment.cumulative_distance_km.toFixed(1)} km地点
                        <span className={styles.selectedSegmentTime}>
                          到達予想 {formatSegmentArrivalTime(selectedRouteSegment.segment.estimated_arrival_time)}
                        </span>
                      </span>
                      <button
                        type="button"
                        className={styles.selectedSegmentClearButton}
                        aria-label="区間の選択を解除"
                        onClick={() => setSelectedRouteSegment(null)}
                      >
                        ×
                      </button>
                    </div>
                    <AxisContributionBar
                      axes={axisCatalog.axes}
                      contributions={selectedRouteSegment.segment.axis_contributions}
                      axisColors={axisCatalog.axisColors}
                    />
                    {researchEnabled && Object.keys(selectedRouteSegment.segment.material_values).length > 0 && (
                      <ul className={styles.selectedSegmentMaterialValues}>
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
              </Tabs.Content>
            ))}
            {showComparisonTab && (
              // forceMount: 比較タブを開いていない間もComparisonPanelをマウントし続ける
              // （実験スロットは生成のたびにpage.tsxのstateへ積まれ続けるため、タブが
              // 非アクティブな間だけ更新が止まる状態を避ける。非アクティブ時の非表示は
              // page.module.cssの[data-state="inactive"]セレクタで行う）。
              <Tabs.Content className={styles.outcomeTabPanel} value="comparison" forceMount>
                {/* 比較表の軸は、ライブなroutePreference（「今」の設定）ではなく各スロットの
                  生成時点の重み（conditions.route_preference）を見る——いずれかのスロットで
                  一度でも重み>0だった軸は、現在のroutePreferenceの値に関わらず残す。「今」の
                  設定だけで絞ると、風重み0.5で生成→風の重みを0へ変更→別スロットを生成、と
                  いう手順で両スロットのaxis_difficultiesに風の値が残っていても比較表から
                  風の行が消えてしまい、「重みを変えて何が変わったか比較する」という比較タブ
                  本来の目的と逆行してしまう。 */}
                <ComparisonPanel
                  slots={experimentSlots}
                  axisLabels={axisCatalog.axisLabels}
                  axes={axisCatalog.axes.filter((axis) =>
                    experimentSlots.some((slot) => (slot.conditions.route_preference[axis.axisId] ?? 0) > 0),
                  )}
                  materials={materialCatalog}
                />
              </Tabs.Content>
            )}
          </div>
        </Tabs.Root>
      </>
    );
  }

  // 編集できるのは目的地ルートのみ——周回は起点へ戻る制約があり、途中で別候補へ乗り換えると
  // 戻れる保証が無くなる。条件は**表示中の候補を作った生成**で見る。いまの目的地ピンで見ると、
  // 周回モードへ切り替えた後もピンが残っている間は操作面が出てしまい、合成リクエストが
  // destination無しになって弾かれる。
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
    <div className={styles.viewport}>
      {/* 天候は生成条件（風評価の起点）のため、サイドバー内に埋もれさせず常設ヘッダに
          置く。デスクトップ・モバイル共通の1箇所。 */}
      <header className={styles.weatherHeader} title="風向・風速はルート候補の評価に使われます">
        {/* 風向・風速はルート評価の起点（ヘッダー本来の主目的、header自身のtitle参照）
            であるため、警報バッジより優先して常に見える側に置く: flex-shrink: 0で
            常に自然幅を保ち、position: sticky; left: 0で.weatherHeaderの左端に固定する。
            警報バッジ・デバッグアイコン（.headerActions）は代わりに、入り切らなければ
            スクロールしないと見えない状態を許容する。 */}
        <div className={styles.weatherStats}>
          <WeatherPanel amedas={amedas} loading={amedasLoading} error={amedasError} />
          {/* 「今日の見通し」（日没・今日の降水確率最大・最大風速・気温レンジ）。
              .weatherStatsと同じ左寄せ固定グループに含め、警報バッジより優先して常に
              見える側に置く（瞬間値のWeatherPanelとは別枠のトグルにする）。 */}
          <TodayOutlook weather={weather} loading={weatherLoading} error={weatherError} />
        </div>
        <div className={styles.headerActions}>
          <WarningBadgeList items={warningBadgeItems} failures={warningFetchFailures} />
          {/* 研究モードON/OFF・デバッグログ表示アイコンを1個のメニューへ集約する
              （ヘッダーの個別ボタンを増やさないため）。debugEnabled時のみデバッグログ項目を
              表示（デバッグモードのON/OFF自体は/adminで切り替える、DebugConsole.tsx参照）。
              DebugConsole自体はposition:fixedのFloatingPanelベースで自己完結しており、
              JSXツリー上のどこに置いても見た目は変わらない。 */}
          <div className={styles.headerMenuSlot}>
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
            <button
              type="button"
              onClick={() => setSidebarCollapsed((v) => !v)}
              aria-label={sidebarCollapsed ? "パネルを開く" : "パネルを閉じる"}
              className={styles.toggleButton}
            >
              {sidebarCollapsed ? "☰" : "✕"}
            </button>

            {!sidebarCollapsed && (
              <>
                {/* サイドバーはモバイルの下部タブと同じ区分・同じ順序（「ルート設定」＝
                    生成ボタンで反映／「ルート結果」＝読むだけ）。ルートの編集は
                    「ルート結果」の中のモードで、独立した区分を持たない。各区分は独立して
                    開閉し、開閉状態はlocalStorageへ保存する。 */}
                {/* タブ列（見出し行）とタブの中身（本文）の両方を囲む。 */}
                <Tabs.Root value={settingsTab} onValueChange={(value) => setSettingsTab(value as SettingsTab)}>
                  <Disclosure
                    className={styles.blockSection}
                    headerClassName={styles.blockHeaderRow}
                    triggerClassName={styles.blockSummary}
                    bodyClassName={styles.blockBody}
                    id={GENERATE_SECTION_TITLE_ID}
                    summary={
                      <>
                        <span aria-hidden="true" className={styles.blockChevron} />
                        ルート設定
                      </>
                    }
                    trailing={
                      <div className={styles.routeSectionHeaderRow}>
                        {renderSettingsTabs()}
                        {renderRouteSectionHeaderActions()}
                      </div>
                    }
                    open={generateOpen}
                    onOpenChange={setGenerateOpen}
                  >
                    {renderRouteSectionBody()}
                  </Disclosure>
                </Tabs.Root>

                {/* ルート結果: 見出し行の右側が操作枠（保存・GPX出力・クリア・説明）。
                    候補が無い間は本文が空になるだけで、区分自体は常に出す。 */}
                <Disclosure
                  className={styles.blockSection}
                  headerClassName={styles.blockHeaderRow}
                  triggerClassName={styles.blockSummary}
                  bodyClassName={styles.blockBody}
                  id={OUTCOME_SECTION_TITLE_ID}
                  summary={
                    <>
                      <span aria-hidden="true" className={styles.blockChevron} />
                      ルート結果
                    </>
                  }
                  trailing={
                    routes.length > 0 ? (
                      <div className={styles.outcomeSectionHeaderActions}>{renderRouteResultHeaderActions()}</div>
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

        {/* app-map-paneはglobals.css側のMapLibre帰属表示（オフセット・配色）規則
            （.maplibregl-ctrl-bottom-* と同じ、位置だけを持つマーカークラスの
            手法）が参照するグローバルなマーカークラス。 */}
        {/* 下部シートが占める高さを地図側へ渡す。地図の操作ボタン（現在地・気象タイム
            ライン等）は画面の下端からの距離で置いているため、シートを持ち上げるとその裏へ
            隠れる。CSS側はこの値を足した位置と元の位置の大きい方を使う。 */}
        <div
          ref={mapPaneRef}
          className={`${styles.mapPane} app-map-pane`}
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
            // experimentSlots（研究モード中の生成履歴、1件目は常にEXPERIMENT_SLOT_COLORSの
            // 先頭）は地図側（sceneの役割`slotLine`）が無条件で描画するため、
            // 実際に「比較」タブを見ているとき以外に地図へ残ると選択中ルートの色分けと
            // 紛らわしい。研究モード中の比較用オーバーレイという役割上、
            // comparisonTabActiveの間だけ渡すよう限定する（スロット自体の記録・
            // ComparisonPanelでの一覧表示は researchEnabled のみで動く）。
            experimentSlots={researchEnabled && comparisonTabActive ? experimentSlots : []}
            selectedRouteSegment={selectedRouteSegment}
            // 区間詳細は「ルート結果」を見ている間だけ。編集中は詳細の置き場が編集面へ
            // 置き換わっており、選んでも地図にピンが残るだけになる。
            onRouteSegmentSelect={(selection) => {
              if (!routeInspectionEnabled) return;
              setSelectedRouteSegment(selection);
            }}
            onRouteSelect={handleRouteSelectFromMap}
            // 周回モード中は地図上のピンを表示・追加受付しない（モード切り替え自体は
            // waypoints/destination state自体を消さないため、目的地モードへ戻れば
            // 復元される）。
            waypoints={routeMode === "destination" ? waypoints : []}
            onWaypointRemove={handleWaypointRemove}
            onWaypointMove={handleWaypointMove}
            destination={routeMode === "destination" ? destination : null}
            onDestinationClear={handleDestinationClear}
            armedPinRole={pinPlacementArmedRole}
            pointEditingEnabled={pointEditingEnabled}
            onPinPlace={handlePinPlace}
            onOriginSet={setManualLocation}
            measureRouteFitObscuredPx={measureRouteFitObscuredPx}
          />

          <LensControl {...mapView.lensControl} />

          <MapOverlayControls {...mapView.overlayControls} />

          {/* 地図下部中央の行。「まとめて元に戻す」操作を並べる（design-principles.md
              「UI仕様」: 地図の視界を圧迫しない）。レイヤーのON/OFFと凡例の絞り込みは
              別の状態のため、戻す操作も別々に要る。 */}
          <div ref={bottomControlRowRef} className={styles.bottomControlRow}>
            <button
              type="button"
              onClick={mapView.bulk.hideAllLayers}
              disabled={!mapView.bulk.anyLayerOn}
              aria-label="表示中のレイヤーをすべて非表示にする"
              title="表示中のレイヤーをすべて非表示にする"
              className={styles.clearAllButton}
            >
              <ClearAllLayersIcon size={14} />
            </button>
            <button
              type="button"
              onClick={mapView.bulk.showAllLegendRows}
              disabled={!mapView.bulk.anyLegendHidden}
              aria-label="絞り込みをすべて解除する"
              title="絞り込みをすべて解除する"
              className={styles.clearAllButton}
            >
              <ClearAllFiltersIcon size={14} />
            </button>
            {/* このページが持つ地図インスタンスだけを描き直す。押した人の
                画面にしか影響しない純粋なクライアント操作で、サーバー側のタイルキャッシュには
                触れない（そちらは全利用者へ影響するため/adminのTileCachePanelにある）。
                ページ全体を再読み込みすると生成済みのルート候補が消えるため、地図だけを
                描き直す入口をここへ残す。 */}
            <button
              type="button"
              onClick={mapView.bulk.redraw}
              aria-label="地図の表示を再描画する"
              title="地図の表示を再描画する"
              className={styles.clearAllButton}
            >
              <RedrawMapIcon size={14} />
            </button>
          </div>

          {/* 走行方位（風・勾配の評価に使う向き）。出発時刻・想定速度と同じ走行条件の一部として
              常時表示する（MapLibreのズーム/回転コントロールの下）。 */}
          <TravelBearingControl value={travelBearingDeg} onChange={setTravelBearingDeg} />

          {/* 走行条件（出発時刻・想定速度）。走行方位アイコンの直下（地図右上）へ積む
              （狭いスマホ画面でも地図の視界を圧迫しないよう、地図上部中央のレンズピルとは
              別のアイコン列にする）。出発時刻は気象レイヤーの表示時刻と同じ共有state
              （出発時刻）。 */}
          <div className={styles.rideConditionColumn}>
            <RideConditionBar
              departureTime={departure.at}
              onDepartureTimeChange={departure.setAt}
              onDepartureNow={departure.followNow}
              speedKmh={assumedSpeedKmh}
              onSpeedKmhChange={setAssumedSpeedKmh}
            />
          </div>

          <button
            type="button"
            onClick={handleLocateMe}
            disabled={locating}
            aria-label="現在地に移動"
            title="現在地に移動"
            className={locating ? `${styles.locateButton} ${styles.locateButtonBusy}` : styles.locateButton}
          >
            {locating ? (
              "…"
            ) : (
              // フォントに依存しないSVGアイコン（十字線+中心ドット、地図アプリの現在地
              // アイコンの定番形状）を使う——Unicode文字「◎」は書体によって中央のドットを
              // 描画せず単なる白丸に見えることがある。
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

          {locateError && <p className={styles.locateError}>{locateError}</p>}
        </div>
      </div>

      {/* モバイル: 下部タブバー＋部分シート（「ルート設定」「ルート結果」。地図の見え方は
          シートではなく地図上のチップで操作する）。各タブはアイコン+1行ラベル（地図上のiconChip、
          MapOverlayControls.module.cssと同じ構成）。「ルート結果」タブには、設定変更後
          未反映（conditionsDirty）に気づけるよう小さいバッジを付ける。シート表示中も
          地図の上側が見えたままパン/ズームできる（暗幕なし、詳細はBottomSheetの
          コメント参照）。 */}
      {isMobile && (
        <>
          <nav ref={mobileTabBarRef} className={styles.mobileTabBar} aria-label="パネル切り替え">
            <button
              type="button"
              aria-expanded={mobileSheet === "routeSettings"}
              onClick={() => handleMobileTabClick("routeSettings")}
              className={
                mobileSheet === "routeSettings" ? `${styles.tabButton} ${styles.tabButtonActive}` : styles.tabButton
              }
            >
              <RouteSettingsIcon />
              <span className={styles.tabLabel}>ルート設定</span>
            </button>
            <button
              type="button"
              aria-expanded={mobileSheet === "routeOutcome"}
              onClick={() => handleMobileTabClick("routeOutcome")}
              className={`relative ${
                mobileSheet === "routeOutcome" ? `${styles.tabButton} ${styles.tabButtonActive}` : styles.tabButton
              }`}
            >
              <RouteIcon />
              <span className={styles.tabLabel}>ルート結果</span>
              {/* conditionsDirty（生成前に条件が変わった）とhasUnseenResults（生成が完了し
                  新しい結果が用意できた）の両方をこのドットで知らせる。前者は生成完了と
                  同時に消える一方後者は生成完了時に立つため、生成の前後を通じて「ルート
                  結果タブを見るべきタイミング」の合図が途切れない。 */}
              {(conditionsDirty || hasUnseenResults) && <span aria-hidden="true" className={styles.dirtyDotOnTab} />}
            </button>
          </nav>

          <Tabs.Root value={settingsTab} onValueChange={(value) => setSettingsTab(value as SettingsTab)}>
            <BottomSheet
              open={mobileSheet === "routeSettings"}
              onClose={() => setMobileSheet(null)}
              title="ルート設定"
              titleId={ROUTE_SETTINGS_SHEET_TITLE_ID}
              headerLead={renderSettingsTabs()}
              headerAction={renderRouteSectionHeaderActions()}
              heightVh={mobileSheetHeightVh}
              onHeightChange={handleMobileSheetHeightChange}
              onHeightCommit={handleMobileSheetHeightCommit}
              autoFitHeight={!sheetHeightChosen}
              fitKey={`${settingsTab}:${routeMode}`}
            >
              {renderRouteSectionBody()}
            </BottomSheet>
          </Tabs.Root>

          <BottomSheet
            open={mobileSheet === "routeOutcome"}
            onClose={() => setMobileSheet(null)}
            title="ルート結果"
            titleId={ROUTE_OUTCOME_SHEET_TITLE_ID}
            headerAction={routes.length > 0 ? renderRouteResultHeaderActions() : undefined}
            heightVh={mobileSheetHeightVh}
            onHeightChange={handleMobileSheetHeightChange}
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
