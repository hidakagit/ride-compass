"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import Disclosure from "@/components/Disclosure/Disclosure";
import { Button } from "@/components/ui/Button/Button";
import MapView, { type RouteFitObscuredPx } from "@/components/Map/MapView";
import MapOverlayControls, { type OverlayLayerChip } from "@/components/MapOverlayControls/MapOverlayControls";
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
import {
  buildMapLayers,
  deriveFetchLayerStatus,
  isAxisStudioLayer,
  type LayerDataStatus,
  type LayerDataStatusByLayer,
  type MapLayerId,
  buildDefaultLayerVisibility,
  TILE_ZOOM_TOO_WIDE_NOTICE,
  UNUSED_LEGEND_FILTER,
  TILE_VERSIONS_MISSING_NOTICE,
  tileVersionGatedLayerIds,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import { axisMapLayerId, buildAxisRampLegend, dedicatedWayValueMapLayerId } from "@/components/Map/axisLayers";
import { dedicatedWayValueLegend, type DedicatedWayValueDisplay } from "@/components/Map/dedicatedWayValueLayer";
import LensControl, { type LensOption } from "@/components/LensControl/LensControl";
import type { LegendEntry } from "@/components/Map/legendFilter";
import { primaryAttributeIdsToLayerIds } from "@/components/Map/primaryAttributes";
import { type LegendFilterSummaryAxis } from "@/components/Map/legendFilter";
import type { DisasterSourceKey } from "@/components/Map/dynamicWeather";
import { ROAD_FILTER_AXES, type RoadFilterAxisId } from "@/components/Map/roadFilterAxes";
import { buildStaticFilterAxes, type StaticFilterAxisId } from "@/components/Map/staticAttributeLayers";
import {
  DEFAULT_ROUTE_STYLE_MODE_ID,
  LENS_DIFFICULTY_ID,
  LENS_NEUTRAL_COLOR,
  LENS_NONE_ID,
  getRouteStyleMode,
  isRouteStyleModeId,
  type LensId,
} from "@/components/Map/routeStyleModes";
import ErrorText from "@/components/ErrorText/ErrorText";
import RouteForm, { type RouteMode, type SettingsTab } from "@/components/RouteForm/RouteForm";
import { useRouteFormSubmit } from "@/components/RouteForm/useRouteFormSubmit";
import RouteSettingsPanel, { stackBarColorForIndex } from "@/components/RouteSettingsPanel/RouteSettingsPanel";
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
import type { MapViewport } from "@/components/Map/windLayer";
import { THUNDER_ACTIVITY_LEVELS, TORNADO_POTENTIAL_LEVELS } from "@/components/Map/thunderNowcast";
import { RISK_LEVEL_COLORS } from "@/components/Map/riskMap";
import { useDynamicWeatherLayers } from "@/hooks/useDynamicWeatherLayers";
import { dedicatedWayValuesFor, useDedicatedWayValues } from "@/hooks/useDedicatedWayValues";
import { useWeatherConditions } from "@/hooks/useWeatherConditions";
import { CLIENT_TUNING_IDS, clientTuningValue, useAxisCatalog } from "@/hooks/useAxisCatalog";
import { useTileVersionsReady } from "@/hooks/useTileVersionsReady";
import { useMaterialCatalog } from "@/hooks/useMaterialCatalog";
import { syncHardFilterKeys } from "@/lib/hardFilterSync";
import { buildGenerateRequest, generationConditionsKey, type GenerationInput } from "@/lib/generationRequest";
import { syncRoutePreferenceKeys } from "@/lib/routePreferenceSync";
import { DEFAULT_ROUTE_PREFERENCE } from "@/lib/evaluationAxes";
import { formatMaterialValue, materialCatalogLabel } from "@/lib/axisMaterialsCatalog";
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
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { debugLog } from "@/lib/debugLog";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useElementHeightCssVar } from "@/hooks/useElementHeightCssVar";
import { useIsomorphicLayoutEffect } from "@/hooks/useIsomorphicLayoutEffect";
import { useLocation } from "@/hooks/useLocation";
import { useStoredState, useStoredBooleanState, useStoredJsonState } from "@/hooks/useStoredState";
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
// 凡例の絞り込みチェックを地図へ反映するまでの猶予。チェック自体は即時反映が原則だが、
// 連続タップのたびにMapLibreのフィルタ再適用を走らせない（useDebouncedValue参照）。
// 道路情報の2軸に加え、車ストレス・指定路線・停止要因POI・事故（当事者/重大度）の
// 絞り込みにも同じ猶予を適用する。
const LEGEND_FILTER_DEBOUNCE_MS = 400;

// 色分けモード（ルート）の保存先。プライベートブラウジング等でlocalStorageが
// 使えない環境があるため、読み書きとも失敗はデフォルトモードへのフォールバックとして
// 握りつぶす。路面側は色分けモードを持たない（常に固定色。roadFilterAxes.ts参照）ため
// 対応する保存先は無い。
// レンズ（地図を何で塗るか）。保存キーはルート線の色分けモードと共通（同じ値を指す）。
const ROUTE_STYLE_MODE_STORAGE_KEY = "ridecompass:route-style-mode";
const LENS_KEEP_AFTER_ROUTE_STORAGE_KEY = "ridecompass:lens-keep-after-route";

// 地図の見え方（系統B、レイヤーのON/OFF・絞り込み・レンズ）の設定はすべてlocalStorageへ
// 保存し、リロード後も復元する。
// 生成条件（系統A）のうち、ルート設定パネルが操作する評価の設定（重み・0次除外）も
// 保存する——同じパネルで並んでいる設定の片方だけが消えると、利用者は何が残るか予測
// できない。毎回初期化するのは「その場で決まる」出発地点・距離だけにする。
const LAYER_VISIBILITY_STORAGE_KEY = "ridecompass:layer-visibility";
// layerVisibility.routeは「候補線・ハロー・矢印・色分けレイヤー全体」を指す。過去に
// 明示的にfalseへ変更・保存していた利用者は、更新後にルートを生成しても地図に候補線が
// 1本も出ない状態から始まってしまう（復帰手段の地図チップもhasDetail成立まで無効化
// されているため気づきにくい）。1回限りの移行マーカー——このキーが無い間だけ
// route:falseをtrueへ強制し、以後はユーザーの選択どおり保存・復元する。
const ROUTE_LAYER_MEANING_MIGRATED_STORAGE_KEY = "ridecompass:route-layer-meaning-migrated-v1";
const HIDDEN_LEGEND_KEYS_STORAGE_KEY = "ridecompass:hidden-legend-keys";
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

// 地図チップ・サイドバーからON/OFFできるレイヤーの既定値。記述子の`defaultOn`から導く
// （レイヤーを足してもここは変わらない。既定ONにするかはレイヤーの性質の側で宣言する）。
//
// 「道路情報」（road）はroadType/roadSurfaceという別々のレイヤーへ分かれている。
// 旧保存値（road: boolean）からの移行処理はuseStoredStateのdeserialize（下記）参照。線状降水帯予測マップは
// 「降水」チップの傘下へ統合されており、個別のキーを持たない（hooks/
// useDynamicWeatherLayers.ts参照）。
const DEFAULT_LAYER_VISIBILITY: MapLayerVisibility = buildDefaultLayerVisibility();

// 「どのモードでも非表示カテゴリ無し」を表す共通の空配列。useStateの外に置いて参照を
// 固定し、MapView側のエフェクト依存（hidden*LegendKeys）が毎レンダーで発火しないようにする。
const NO_HIDDEN_LEGEND_KEYS: string[] = [];

// 災害チップの要素トグルの保存先ID（hiddenLegendKeysByModeのキー）。実際の絞り込み軸
// （路面の種類等）のIDと衝突しないよう、レイヤーIDそのものを使う。
const DISASTER_SOURCE_AXIS_ID = "disaster";

// 災害チップの▶パネルに出す「表示する情報」（ソースごとの個別トグル）。axisIdを持つため
// LegendCheckboxListで描画され、非表示キーはhiddenLegendKeysByMode[DISASTER_SOURCE_AXIS_ID]
// へ保存される（▶パネルの絞り込みと同じ保存先・同じ操作感）。
// 面同士は重なると混色して危険度を読み取れないため、混んできたらここで絞り込む。
// keyは`DISASTER_SOURCES`（dynamicWeather.ts）と一致していなければならない。型で縛る。
const DISASTER_SOURCE_LEGEND: (LegendEntry & { key: DisasterSourceKey })[] = [
  { key: "heavyRain", label: "大雨キキクル", color: RISK_LEVEL_COLORS[2].color, filter: UNUSED_LEGEND_FILTER },
  { key: "landslide", label: "土砂災害キキクル", color: RISK_LEVEL_COLORS[2].color, filter: UNUSED_LEGEND_FILTER },
  { key: "inundation", label: "浸水キキクル", color: RISK_LEVEL_COLORS[2].color, filter: UNUSED_LEGEND_FILTER },
  { key: "flood", label: "洪水キキクル（河川）", color: RISK_LEVEL_COLORS[2].color, filter: UNUSED_LEGEND_FILTER },
  { key: "thunder", label: "雷ナウキャスト", color: THUNDER_ACTIVITY_LEVELS[1].color, filter: UNUSED_LEGEND_FILTER },
  { key: "tornado", label: "竜巻発生確度", color: TORNADO_POTENTIAL_LEVELS[0].color, filter: UNUSED_LEGEND_FILTER },
  { key: "liden", label: "落雷（発生地点）", color: "#facc15", filter: UNUSED_LEGEND_FILTER },
];

// 災害チップの凡例。precipitation/wind凡例と同じパターン（表示専用、filterはダミー値）で、
// 危険度の色の意味を要素の種類ごとに並べる。実データ（活動度・発生確度・危険度5段階の
// ラベルと近似色）はthunderNowcast.ts・riskMap.tsが単一の情報源。キキクル4種は4つとも
// 同じ5段階配色のため、凡例も1ブロックにまとめる。
const DISASTER_LEGEND_DETAILS_BASE: readonly LegendFilterSummaryAxis[] = [
  {
    label: "キキクル（土砂災害・大雨・浸水・洪水）",
    legend: RISK_LEVEL_COLORS.map((level) => ({ ...level, filter: UNUSED_LEGEND_FILTER })),
    hiddenKeys: NO_HIDDEN_LEGEND_KEYS,
  },
  {
    label: "雷ナウキャスト（活動度）",
    legend: THUNDER_ACTIVITY_LEVELS.map((level) => ({ ...level, filter: UNUSED_LEGEND_FILTER })),
    hiddenKeys: NO_HIDDEN_LEGEND_KEYS,
  },
  {
    label: "竜巻発生確度ナウキャスト",
    legend: TORNADO_POTENTIAL_LEVELS.map((level) => ({ ...level, filter: UNUSED_LEGEND_FILTER })),
    hiddenKeys: NO_HIDDEN_LEGEND_KEYS,
  },
];

// 「ルートを作る」セクション見出しのDOM id。デスクトップの<summary>専用（モバイルは
// 「ルート設定」「ルート結果」の2タブへ分割しているため、専用の
// ROUTE_SETTINGS_SHEET_TITLE_ID/ROUTE_OUTCOME_SHEET_TITLE_IDを別途持つ）。
const GENERATE_SECTION_TITLE_ID = "generate-section-title";
const OUTCOME_SECTION_TITLE_ID = "outcome-section-title";
// モバイルの「ルート設定」「ルート結果」シート見出しのDOM id。
const ROUTE_SETTINGS_SHEET_TITLE_ID = "route-settings-sheet-title";
const ROUTE_OUTCOME_SHEET_TITLE_ID = "route-outcome-sheet-title";

type MobileSheet = "routeSettings" | "routeOutcome" | null;

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
  // それらより前で宣言する必要がある。取得完了までとエラー時は静的フォールバック
  // （axisLayers.ts: RAMP_AXES等）を返すため、呼び出し側は常に何かしらの一覧を受け取れる。
  const axisCatalog = useAxisCatalog();
  // 比較パネル（研究モード）の材料値行（material_values）のラベル・単位表記に使う
  // （ComparisonPanel.tsx参照）。
  const materialCatalog = useMaterialCatalog();

  const [routes, setRoutes] = useState<RouteCandidate[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  // 区間の乗り換え（docs/tasks/T621.md）。比較相手と、相手の道を選んだ区間の位置。
  // 区間の位置はstretchesの添字で持つ——edge_idsの位置で持つと、候補が入れ替わったときに
  // 別の場所を指したまま残る。
  // 区間ごとに選んだ道（グループの位置→代替のkey）。相手を1本選ぶ形は持たない。
  // 適用した乗り換えを積み上げる。各要素の範囲は「適用した時点の経路」に対する位置のため、
  // 途中だけを外すことはできない（戻せるのは直前の1手）。
  const [appliedAlternatives, setAppliedAlternatives] = useState<StretchAlternative[]>([]);
  // 編集中の元ルート。nullなら「ルート結果」は通常の一覧、非nullなら同じ場所が編集面に
  // なる（独立したタブにすると、どのルートを編集しているのかを選び直す形になる）。
  const [editingRouteId, setEditingRouteId] = useState<string | null>(null);
  const [splicing, setSplicing] = useState(false);
  // 「新しいルートを作る」の実行中フラグ。stateと違い同じタスク内で即座に読めるため、
  // 連打の2回目をここで止める。
  const applyingRef = useRef(false);
  // 「差分を見る」で評価した結果。組み合わせをキーに覚える——選び直して戻ったときに
  // 投げ直さない（生成APIは1分10回の上限があり、評価自体も温で1秒前後かかる）。
  const [splicePreviews, setSplicePreviews] = useState<Record<string, RouteCandidate>>({});
  const [previewing, setPreviewing] = useState(false);
  // 合成の失敗は「ルート結果」欄の空状態には出ない（候補がある間は描かれない）。
  // 押した場所＝編集パネルに出す。
  const [spliceError, setSpliceError] = useState<string | null>(null);
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
  const [loading, setLoading] = useState(false);
  // ルート生成のバックグラウンドジョブ化に伴う進捗表示。生成中(loading)の間だけ意味を
  // 持ち、待ち(queued)/実行中(running)の別と経過時間をボタン文言へ反映する
  // （RouteForm.tsx: progressLabel参照）。生成開始直後・完了直後はnull
  // （queued/runningのどちらかが確定するまでの一瞬はloadingのみでラベルを出さない）。
  const [generationProgress, setGenerationProgress] = useState<GenerationProgress | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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
  // handleGenerate/MapView.tsxのpinPlacementEnabled参照）。
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
  // 生成したときの条件と現在のフォーム値を比較して「条件が変更されています」ヒントを
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
  // 仮定巡航速度（backend: RouteGenerateRequest.assumed_speed_kmh、km/h）。距離と同じく
  // string stateのまま保持し、送信時にNumber化する。区間の通過予定時刻（探索時の風の時刻
  // 選択）・到達予想時刻の基準になるため全モードで送る。
  const [assumedSpeedKmh, setAssumedSpeedKmh] = useState<number>(routeGenerateConfig.default_assumed_speed_kmh);
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
    // 生成に実際に送った入力そのもの。区間の乗り換え（docs/tasks/T621.md）で合成した
    // 経路も**同じ条件で**評価するために使う——合成結果は素の結果と本質的に区別せず、
    // 同じ並びへ差し込まれるため、条件が違うと比較できない値で順位が決まる。
    // エコー（`conditions`）ではなく入力を持つのは、エコーが`lens_axis_id`を含まない
    // ため（区間表示用の軸評価が候補ごとに食い違う）。
    input: GenerationInput;
  } | null>(null);
  // 表示中のルートを実際に生成した瞬間のroute_preference（重み）。routePreference自体は
  // ルート設定パネルが常時編集するライブなstateのため、生成後に再生成せず重みだけ変更すると、
  // 表示中のルートが実際に評価された時の重みと「生成したルートの色分け」メニューがズレる。
  // バックエンドは生成に実際に適用したroute_preferenceを`conditions.route_preference`として
  // 既にエコーバックしている（`GenerationConditions`、backend/app/api/routers/routes.py）ため、
  // 生成成功時にここへ複製するだけでよい（バックエンド変更不要）。
  const [generatedRoutePreference, setGeneratedRoutePreference] = useState<RoutePreferenceWeights | null>(null);

  // 評価重みのリクエスト上書き（研究インターフェース改善 §10-1/4）。overrideEnabled=falseの間は
  // 生成リクエストからroute_preferenceを省略し、既存挙動（既定値）を完全に維持する
  // （一般ユーザーには影響しない）。route_preference/routePreference自体は一般向けルート
  // 設定画面（RouteSettingsPanel）とも共有する状態で、withAutoEnableにより、どちらの
  // パネルを操作してもこのフラグが自動でONになる。
  const [weightOverrideEnabled, setWeightOverrideEnabled] = useStoredBooleanState(
    WEIGHT_OVERRIDE_ENABLED_STORAGE_KEY,
    false,
  );
  const [routePreference, setRoutePreference] = useStoredJsonState<RoutePreferenceWeights>(
    ROUTE_PREFERENCE_STORAGE_KEY,
    DEFAULT_ROUTE_PREFERENCE,
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
  // （EXPERIMENT_SLOT_COLORS[0]="#16a34a"=緑）ため、「ルートをクリア」を押した見た目
  // どおり地図が空になるよう、実験スロットも同時にクリアする（比較履歴を残すよりも
  // 「クリアしたら地図が本当に空になる」という一般的な期待を優先）。
  const handleRoutesClear = useCallback(() => {
    setRoutes([]);
    setSelectedRouteId(null);
    setComparisonTabActive(false);
    setGeneratedConditions(null);
    setGeneratedRoutePreference(null);
    setExperimentSlots([]);
    setSelectedRouteSegment(null);
  }, []);

  // MapViewから伝わる現在のビューポート（MapView.tsx: onViewportChange参照）。
  // moveend/zoomendのたびに素の値が来るため、フェッチ用にはデバウンスして使う
  // （useDynamicWeatherLayers/useWeatherGrid内のwindDetailフェッチeffect参照）。
  const [mapViewport, setMapViewport] = useState<MapViewport | null>(null);

  // 地図レイヤーのON/OFF（MAP_LAYERSのid単位。既定値はレイヤー記述子の`defaultOn`から
  // 導かれるため、レイヤーを足してもここへ足すものは無い）。
  // localStorageへの保存・復元はuseStoredState参照。既知のレイヤーID
  // かつboolean値のものだけ採用する（レイヤーの増減や壊れた保存値があっても、残りの設定は
  // 活かしてデフォルトで埋める）。
  //
  // reloadKeyにaxisCatalog.loadedを渡し、マウント直後とカタログ取得完了後の2段階で復元する
  // （useStoredState.ts参照）。キー集合自体はカタログに依存しないが、下の「route:falseの
  // 意味変更」移行が1回目の復元で書き戻した値を、2回目の復元がそのまま読み直せるように
  // 揃えている。
  const [layerVisibility, setLayerVisibility] = useStoredState<MapLayerVisibility>(
    LAYER_VISIBILITY_STORAGE_KEY,
    DEFAULT_LAYER_VISIBILITY,
    {
      serialize: (v) => JSON.stringify(v),
      reloadKey: axisCatalog.loaded,
      deserialize: (raw) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(raw);
        } catch {
          return null;
        }
        if (typeof parsed !== "object" || parsed === null) return null;
        const next: MapLayerVisibility = { ...DEFAULT_LAYER_VISIBILITY };
        const parsedRecord = parsed as Record<string, unknown>;
        // 「道路情報」（road）の論理分割（roadType/roadSurface）に伴う旧保存値の移行。
        // 旧形式（road: boolean、新キーが無い）が残っていれば両方の新キーへ引き継ぐ
        // （新形式で保存済みなら下のループがroadType/roadSurfaceを個別に上書きする）。
        if (
          typeof parsedRecord.road === "boolean" &&
          parsedRecord.roadType === undefined &&
          parsedRecord.roadSurface === undefined
        ) {
          next.roadType = parsedRecord.road;
          next.roadSurface = parsedRecord.road;
        }
        for (const id of Object.keys(next) as MapLayerId[]) {
          const value = parsedRecord[id];
          if (typeof value === "boolean") next[id] = value;
        }
        // 1回限りの移行。マーカーが未設定の間だけroute:falseをtrueへ戻す（旧い意味
        // [色分けレイヤーのみ非表示]で保存された値を、新しい意味[全レイヤー非表示]の
        // まま引き継がせないため）。マーカー自体はroute値に関わらず必ず立て、次回以降は
        // ユーザーの選択どおり尊重する。
        try {
          if (window.localStorage.getItem(ROUTE_LAYER_MEANING_MIGRATED_STORAGE_KEY) == null) {
            if (next.route === false) {
              next.route = true;
              // useStoredStateの復元effect（useStoredState.ts）はsetValueのみを呼びcommit
              // （localStorageへの書き戻し）は行わない。この移行はreloadKey（axisCatalog.loaded）
              // 経由でマウント直後（false）→フェッチ完了後（true）の2回deserializeが走るため、
              // ここで明示的に書き戻さないと、1回目でnext.route=trueへ補正してもlocalStorage上は
              // 元のroute:falseのまま残り、2回目のdeserializeが同じ生値を読み直して補正前の
              // falseへ静かに巻き戻ってしまう（マーカー自体は1回目で立つため2回目は移行
              // ブロックに入らずfalseのまま確定する）。route:falseが復元されるとMapView側の
              // applyRouteLayerVisibility（候補線・ハロー・矢印・区間色分けの4レイヤーを
              // まとめて出し分ける）が全て非表示になる。
              window.localStorage.setItem(LAYER_VISIBILITY_STORAGE_KEY, JSON.stringify(next));
            }
            window.localStorage.setItem(ROUTE_LAYER_MEANING_MIGRATED_STORAGE_KEY, "1");
          }
        } catch {
          // 書き戻し・マーカーいずれかの読み書きに失敗した場合は移行が未完了のまま残る
          // （マーカー未設定なら次回起動時に再試行される。通常のデフォルト値フォールバックにも
          // 引き続き任せる）。
        }
        return next;
      },
    },
  );
  // 2次（車の圧迫感・ramp軸）を太く半透明な下敷きにするのは、その材料（1次、
  // primaryAttributeIdsToLayerIds）が1つでも同時に表示されているときだけにする。材料が
  // 1つも表示されていなければ、下に隠すものが無いため通常の太さ・不透明度で表示する
  // （常に太く半透明にすると、道路網が密な都市部で下敷きの重なりだけで地図全体がぼやけて
  // 見えてしまう）。軸→一次属性の解決はaxisCatalog.secondaryAxes（実行時カタログ、
  // GUI作成軸を含む）のprimaryAttributeIdsから行う。
  const secondaryAxisCasingLayerIds = useMemo(
    () =>
      axisCatalog.secondaryAxes
        .filter((axis) => {
          if (!axis.layerId) return false;
          return primaryAttributeIdsToLayerIds(axis.primaryAttributeIds).some(
            (materialId) => layerVisibility[materialId],
          );
        })
        .map((axis) => axis.layerId as MapLayerId),
    [layerVisibility, axisCatalog.secondaryAxes],
  );
  // レンズ（地図を何で塗るか）: "none" | "difficulty" | 公開軸のaxis_id。ルート前は全道路
  // （rampタイル・専用配信）、ルート後はルート線を同じ識別子で塗る。生成・クリア・候補切替を
  // またいで保持する。保存形式はJSON化しない生文字列（isRouteStyleModeIdによる妥当性検証が
  // JSON.parseを兼ねる）。軸スタジオでunpublishされた軸idは総合難易度へ倒す。
  // reloadKeyにaxisCatalog.loadedを渡す理由はlayerVisibilityと同じ。deserializeの妥当性判定が
  // 実行時カタログ（routeStyleModes）に依存するため、カタログ取得前の1回だけで判定すると、
  // ビルド後に公開された軸をレンズに選んでいた利用者の保存値が「未知のid」として捨てられ、
  // 再訪のたびに無言で総合難易度へ戻る。
  const [lens, setLens] = useStoredState<LensId>(ROUTE_STYLE_MODE_STORAGE_KEY, DEFAULT_ROUTE_STYLE_MODE_ID, {
    serialize: (v) => v,
    reloadKey: axisCatalog.loaded,
    deserialize: (raw) => (isRouteStyleModeId(axisCatalog.routeStyleModes, raw) ? raw : null),
  });
  const routeStyleModes = axisCatalog.routeStyleModes;
  useEffect(() => {
    if (routeStyleModes.some((mode) => mode.id === lens)) return;
    debugLog(
      "map:route-style-mode",
      `lens "${lens}" is not a known axis id, falling back to "${LENS_DIFFICULTY_ID}"`,
      { requestedId: lens, availableIds: routeStyleModes.map((mode) => mode.id) },
      "warn",
    );
    setLens(LENS_DIFFICULTY_ID);
  }, [routeStyleModes, lens, setLens]);
  // ルート確定後も周囲の道路（全道路の塗り）を残すか。
  const [lensKeepAfterRoute, setLensKeepAfterRoute] = useStoredBooleanState(LENS_KEEP_AFTER_ROUTE_STORAGE_KEY, true);
  // 凡例タップで非表示にしたカテゴリ（モード別に保持。モードを行き来しても各モードの
  // 取捨選択が残る）。路面モードとルートモードのIDは互いに重複しないため1つのレコードで
  // 両系統を管理できる。「文字列の配列」の形のエントリだけ復元時に採用する。
  const [hiddenLegendKeysByMode, setHiddenLegendKeysByMode] = useStoredState<Record<string, string[]>>(
    HIDDEN_LEGEND_KEYS_STORAGE_KEY,
    {},
    {
      serialize: (v) => JSON.stringify(v),
      deserialize: (raw) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(raw);
        } catch {
          return null;
        }
        if (typeof parsed !== "object" || parsed === null) return null;
        const entries = Object.entries(parsed as Record<string, unknown>).filter(
          (entry): entry is [string, string[]] =>
            Array.isArray(entry[1]) && entry[1].every((key) => typeof key === "string"),
        );
        return entries.length > 0 ? Object.fromEntries(entries) : null;
      },
    },
  );
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

  // タイルの最小ズームを宣言したレイヤーのうち、いまのズームでは要求されないもの
  // （MapView.tsx: onTileZoomTooWideChange）。どのレイヤーが対象かも閾値も記述子が持つ。
  const [tileZoomTooWideLayerIds, setTileZoomTooWideLayerIds] = useState<readonly MapLayerId[]>([]);
  // レイヤーごとのデータ取得状態。MapViewが実際のタイル取得結果（sourcedata/
  // sourcedataloading/errorイベント）から算出する（動的気象レイヤーを除く、下記
  // layerDataStatusのuseMemo参照）。
  const [mapViewLayerDataStatus, setMapViewLayerDataStatus] = useState<LayerDataStatusByLayer>({});
  const [refreshToken, setRefreshToken] = useState(0);

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

  // 区間の乗り換え（docs/tasks/T621.md・T808）の導出値。edge_idsの集合演算だけで求まる
  // （軸の計算式は持たない。構造仕様1）。**区間を主語に、その区間の代替を候補横断で並べる**。
  // 編集対象は`routes`から引く（`editingRouteId`を単独で見ない）。候補が入れ替わった・
  // 消えたときに編集モードだけが生き残ると、地図の地点編集・候補選択が無言で無効のまま
  // 戻せなくなる（docs/tasks/T874.md）。
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
  const splicePreview = splicePreviews[spliceChoiceKey] ?? null;
  // 地図の帯をタップしたら、その道へ乗り換える。次に選べる区間はこの結果から求め直すため、
  // 乗り換えた先の道の上にある分かれ道がそのまま次の帯になる。
  const handleSpliceStretchSelect = useCallback(
    (index: number) => {
      const option =
        spliceGroups[Math.floor(index / SPLICE_OPTIONS_PER_GROUP)]?.options[index % SPLICE_OPTIONS_PER_GROUP];
      if (!option) return;
      setSpliceError(null);
      setAppliedAlternatives((current) => [...current, option]);
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
  // だと、ルート全体がシートの裏へ収まって1本も見えない。覆われている高さをMapViewへ渡す。
  // タブバーの高さはCSS（--mobile-tabbar-height）が正のため実測し、シートは高さ自体を
  // vhで持っている（BottomSheet）ためビューポート高から換算する。
  const mobileTabBarRef = useRef<HTMLElement>(null);
  const [mobileViewportMetrics, setMobileViewportMetrics] = useState({ tabBarPx: 0, innerHeightPx: 0 });
  useIsomorphicLayoutEffect(() => {
    const measure = () =>
      setMobileViewportMetrics({
        tabBarPx: mobileTabBarRef.current?.getBoundingClientRect().height ?? 0,
        innerHeightPx: window.innerHeight,
      });
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [isMobile]);
  const routeFitObscuredPx = useMemo<RouteFitObscuredPx | undefined>(() => {
    if (!isMobile) return undefined;
    const sheetPx = mobileSheet ? (mobileViewportMetrics.innerHeightPx * mobileSheetHeightVh) / 100 : 0;
    return { bottom: mobileViewportMetrics.tabBarPx + sheetPx };
  }, [isMobile, mobileSheet, mobileSheetHeightVh, mobileViewportMetrics]);

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
  // このファイル自身の凡例・絞り込み計算（staticLegendHiddenKeysByAxis・
  // staticFilterLegendDetails、下記）は、軸スタジオで新規公開したramp軸の凡例・絞り込み
  // 操作をこの画面のサマリ表示・▶パネルへ反映できるよう、mapLayers/
  // roadSurfaceSharedLayerIdsと同じくaxisCatalog.rampAxesから都度組み立てる
  // （ビルド時静的buildStaticFilterAxes()は使わない）。
  const staticFilterAxes = useMemo(() => buildStaticFilterAxes(axisCatalog.rampAxes), [axisCatalog.rampAxes]);
  // 道路情報以外の絞り込み可能レイヤー（車ストレス・自転車インフラ・指定路線・
  // 停止要因POI・事故の当事者/重大度）。roadHiddenKeysByModeと同じ理由でuseMemoにより
  // 参照を安定させる。
  const staticLegendHiddenKeysByAxis = useMemo(
    () =>
      Object.fromEntries(
        staticFilterAxes.map((axis) => [axis.axisId, hiddenLegendKeysByMode[axis.axisId] ?? NO_HIDDEN_LEGEND_KEYS]),
      ) as unknown as Record<StaticFilterAxisId, readonly string[]>,
    [staticFilterAxes, hiddenLegendKeysByMode],
  );
  const hiddenRouteLegendKeys = hiddenLegendKeysByMode[lens] ?? NO_HIDDEN_LEGEND_KEYS;
  const toggleHiddenLegendKey = useCallback(
    (modeId: string, key: string) => {
      setHiddenLegendKeysByMode((prev) => {
        const current = prev[modeId] ?? [];
        const nextKeys = current.includes(key) ? current.filter((k) => k !== key) : [...current, key];
        return { ...prev, [modeId]: nextKeys };
      });
    },
    [setHiddenLegendKeysByMode],
  );
  // 凡例カテゴリの「すべて表示/すべて隠す」一括操作（1軸分の非表示キー全体の置き換え）。
  // 個別チェックはtoggleHiddenLegendKeyをそのまま使う（絞り込みは即時反映）。
  const setHiddenLegendKeysForAxis = useCallback(
    (axisId: string, hiddenKeys: string[]) => {
      setHiddenLegendKeysByMode((prev) => ({ ...prev, [axisId]: hiddenKeys }));
    },
    [setHiddenLegendKeysByMode],
  );
  const handleRouteLegendToggle = useCallback(
    (key: string) => toggleHiddenLegendKey(lens, key),
    [lens, toggleHiddenLegendKey],
  );
  const handleLensLegendSetHidden = useCallback(
    (hiddenKeys: string[]) => setHiddenLegendKeysForAxis(lens, hiddenKeys),
    [lens, setHiddenLegendKeysForAxis],
  );
  // RouteAxisProfileの軸チップの色ドットを、RouteSettingsPanelの凡例チップと同じ色に
  // する（同じ軸なら両パネルで同じ色、という視覚的な一貫性のため）。
  // stackBarColorForIndexは表示順index・軸総数（catalog.axes.length）から色相環を
  // 等分するため、両パネルとも同じaxisCatalog.axesの並び順・件数を渡す必要がある。
  const axisChipColors = useMemo(() => {
    const colors: Record<string, string> = {};
    axisCatalog.axes.forEach((axis, index) => {
      colors[axis.axisId] = stackBarColorForIndex(index, axisCatalog.axes.length);
    });
    return colors;
  }, [axisCatalog.axes]);
  // 「絞り込みを一括クリア」（ゆる～と等の地図ポータルの「消去」ボタンを参考に追加）。
  // 軸ごとの「すべて表示」を1つずつ押させず、道路情報・車ストレス等の全軸＋ルート凡例の
  // 非表示キーを一度に空へ戻す。レイヤーのON/OFF（layerVisibility）は「絞り込み」とは別の
  // 状態（どのレイヤーを表示するか）のため、ここでは触らない。
  const hasHiddenFilters = useMemo(
    () => Object.values(hiddenLegendKeysByMode).some((keys) => keys.length > 0),
    [hiddenLegendKeysByMode],
  );
  const handleClearAllFilters = useCallback(() => setHiddenLegendKeysByMode({}), [setHiddenLegendKeysByMode]);

  // 地図への反映だけデバウンスする（チェックボックス・条件サマリは即時のroadHiddenKeysByMode/
  // staticLegendHiddenKeysByAxisを参照し、MapViewのフィルタ再適用のみ連続タップを1回へまとめる）。
  const debouncedRoadHiddenKeysByMode = useDebouncedValue(roadHiddenKeysByMode, LEGEND_FILTER_DEBOUNCE_MS);
  const debouncedStaticLegendHiddenKeysByAxis = useDebouncedValue(
    staticLegendHiddenKeysByAxis,
    LEGEND_FILTER_DEBOUNCE_MS,
  );

  // MAP_LAYERS（静的フォールバック）ではなく、axisCatalog.rampAxes（実行時フェッチ、
  // 軸スタジオの公開軸を含む）から組み立てたレイヤーカタログを使う。
  const mapLayers = useMemo(
    () => buildMapLayers(axisCatalog.rampAxes, axisCatalog.dedicatedAxes),
    [axisCatalog.rampAxes, axisCatalog.dedicatedAxes],
  );

  // 「推定指標をONにすると材料の観測データレイヤーも連動ON」するカスケードは持たない。
  // 観測グループのメンバーを個別に「表示項目の設定」で非表示にできるため、非表示にした
  // メンバーが推定指標側の操作で裏からONにされてしまうと、非表示設定でチップ自体が
  // 隠れているためユーザーがOFFに戻す手段を失う（「チップからは消えたのに地図には出続ける」
  // 不整合が起きる）。
  //
  // 地図上チップ（道路/環境/スポット）はどれも複数同時にONにできる。重なって読みにくく
  // なった場合は、各チップの▶パネルで要素・カテゴリ単位に絞り込む
  // （MapOverlayControls.tsx: renderLegendDetails）。道路グループの線同士は
  // `line-offset`による並行トラック（MapView.tsx: applyRoadMaterialTrackOffsets）で
  // 重ならずに並ぶ。
  //
  // 軸スタジオ由来のレイヤー（isAxisStudioLayer、ramp軸・専用way値配信軸）は地図上チップ
  // にもサイドバーにも現れず、layerVisibilityの対象外——表示ON/OFFはレンズ（LensControl）
  // が単独で持つ（同じ道路の同じ位置を塗り分けるため重ねられず、レンズが常に1つだけ選ぶ）。
  const handleLayerToggle = useCallback(
    (id: MapLayerId, on: boolean) => {
      setLayerVisibility((prev) => ({ ...prev, [id]: on }));
    },
    [setLayerVisibility],
  );

  // レンズを選ぶと、地図上の「ルート」チップ（layerVisibility.route）がOFFなら自動でONにする
  // （選んだのに見えないままだと気づきにくいため）。
  const handleLensChange = useCallback(
    (id: LensId) => {
      setLens(id);
      if (!layerVisibility.route) handleLayerToggle("route", true);
    },
    [layerVisibility.route, handleLayerToggle, setLens],
  );

  // 地図上（MapOverlayControls）のサマリ行に出す「適用中の条件」の1行要約。
  // 「道路情報」は路面の種類（roadSurface）・道路の種類（roadType）へ分かれているため、
  // 軸ごとに個別のサマリ・内訳を持つ。
  // 軸ごとのサマリ・内訳は`ROAD_FILTER_AXES`を走査して作る。軸を名指しして同じ形の
  // ブロックを並べると、軸を1つ足すたびに写経が増える（roadFilterAxes.tsの「軸定義を
  // 1つ足すだけでよい」が成り立たなくなる）。
  const roadAxisPanels = useMemo(() => {
    const legendDetailsByLayerId: Record<string, LegendFilterSummaryAxis[]> = {};
    for (const axis of ROAD_FILTER_AXES) {
      const hiddenKeys = roadHiddenKeysByMode[axis.id] ?? NO_HIDDEN_LEGEND_KEYS;
      legendDetailsByLayerId[axis.layerId] = [{ label: "", legend: axis.legend, hiddenKeys, axisId: axis.id }];
    }
    return { legendDetailsByLayerId };
  }, [roadHiddenKeysByMode]);

  const routeLegendDetails = useMemo<LegendFilterSummaryAxis[]>(
    () =>
      hasDetail
        ? [
            {
              label: "",
              legend: getRouteStyleMode(routeStyleModes, lens).legend,
              hiddenKeys: hiddenRouteLegendKeys,
              axisId: lens,
            },
          ]
        : [],
    [hasDetail, lens, hiddenRouteLegendKeys, routeStyleModes],
  );

  // 道路情報以外の絞り込み可能レイヤーの▶パネルの中身。1つのレイヤーが複数の軸を持つ
  // ことがある（事故は当事者と重大度）ため、そのレイヤーの軸をまとめて渡す。
  const staticFilterLegendDetails = useMemo(() => {
    const result: Partial<Record<MapLayerId, LegendFilterSummaryAxis[]>> = {};
    const layerIds = new Set(staticFilterAxes.map((axis) => axis.layerId));
    for (const layerId of layerIds) {
      const axes = staticFilterAxes
        .filter((axis) => axis.layerId === layerId)
        .map((axis) => ({
          label: axis.label ?? "",
          legend: axis.legend,
          hiddenKeys: staticLegendHiddenKeysByAxis[axis.axisId] ?? NO_HIDDEN_LEGEND_KEYS,
          axisId: axis.axisId,
        }));
      result[layerId] = axes;
    }
    return result;
  }, [staticFilterAxes, staticLegendHiddenKeysByAxis]);

  // 動的気象レイヤー（降水ナウキャスト・風/延長降水予報・雷/竜巻ナウキャスト・キキクル）の
  // フェッチ・共有タイムライン・MapView向け描画ペイロードは`useDynamicWeatherLayers`
  // フックが持つ。各要素は対応するshow*がtrueの間だけフェッチする。overlayLayers
  // （下記）がdataStatusとして参照するため、その手前で定義する。
  // 災害チップ配下のソースのうち、▶パネルで非表示に選ばれているもの。面同士が重なると
  // 混色して危険度を読み取れないため、ユーザーがその場で絞り込めるようにしている
  // （保存先はサイドバーの絞り込みと同じhiddenLegendKeysByMode）。
  const hiddenDisasterSources = hiddenLegendKeysByMode[DISASTER_SOURCE_AXIS_ID] ?? NO_HIDDEN_LEGEND_KEYS;
  const disasterLegendDetails = useMemo<LegendFilterSummaryAxis[]>(
    () => [
      {
        label: "表示する情報",
        legend: DISASTER_SOURCE_LEGEND,
        hiddenKeys: hiddenDisasterSources,
        axisId: DISASTER_SOURCE_AXIS_ID,
      },
      ...DISASTER_LEGEND_DETAILS_BASE,
    ],
    [hiddenDisasterSources],
  );
  const {
    dynamicWeather,
    dynamicWeatherDataStatus,
    dynamicLayerTargetTime,
    setDynamicLayerTargetTime,
    handleDynamicLayerNow,
    departureTimePinned,
  } = useDynamicWeatherLayers({
    visibility: layerVisibility,
    hiddenDisasterSources,
    mapViewport,
  });
  // レイヤーごとのデータ取得状態を1つに統合する。mapViewLayerDataStatus（MapLibreの
  // ソースイベントから算出）とdynamicWeatherDataStatus（動的気象レイヤー、フェッチ
  // 自身のloading/errorから算出）はキーが重ならない（動的気象レイヤーは
  // buildLayerDataSourcesの対象外）ため、マージの優先順位を気にする必要はない。
  const layerDataStatus = useMemo<LayerDataStatusByLayer>(
    () => ({ ...mapViewLayerDataStatus, ...dynamicWeatherDataStatus }),
    [mapViewLayerDataStatus, dynamicWeatherDataStatus],
  );

  // タイル世代が届いていないあいだ、それを要るレイヤーは地図に何も描けない。**どのレイヤーが
  // それに当たるかは数え上げない**——ソース対応表から引く（MapView: tileVersionGatedLayerIds）。
  const tileVersionsReady = useTileVersionsReady();
  const tileVersionGatedIds = useMemo(
    () => (tileVersionsReady ? [] : tileVersionGatedLayerIds(axisCatalog.rampAxes)),
    [tileVersionsReady, axisCatalog.rampAxes],
  );
  // 取得が終わっていない間の「まだ出ていない」と、取得が終わったのに世代が無い
  // （カタログの取得失敗・世代を返さない版のbackendが応答）とを分ける。後者は利用者の
  // 操作では直らないため、理由を出して再読み込みを促す。
  const tileVersionsFailed = !tileVersionsReady && (axisCatalog.loaded || axisCatalog.failed);

  // 地図上のチップ行はレイヤーカタログ（mapLayers）から組み立てる。レイヤーを追加したら
  // 凡例の対応をここへ1行足すだけでよい（チップ・凡例パネルの描画は汎用）。
  const overlayLayers = useMemo<OverlayLayerChip[]>(() => {
    // 凡例はlayer.id→値のルックアップで組み立て、無ければstaticFilterLegendDetailsを
    // フォールバックとして最後に見る。
    // 残るのは**この画面の状態からしか作れない凡例**だけ。配信元が色を持つ表示専用の
    // 凡例は記述子が宣言し（`readOnlyLegend`）、絞り込める凡例は`staticFilterAxes`が出す。
    const legendDetailsByLayerId: Partial<Record<MapLayerId, LegendFilterSummaryAxis[]>> = {
      ...roadAxisPanels.legendDetailsByLayerId,
      // 選択中の候補とレンズで中身が変わる。
      route: routeLegendDetails,
      // 要素ごとの表示ON/OFF（hiddenDisasterSources）を持つ。
      disaster: disasterLegendDetails,
    };
    // 専用way値配信軸（`${axisId}Axis`）・ramp軸（`axis:${string}`）は除く。これらの
    // 表示はレンズ（lens→axisVisibility）だけが決めており、layerVisibility側の値は
    // 表示に影響しない。チップとしても描画されない（評価軸はルート設定パネルへ移設済み、
    // mapLayers.ts: isAxisStudioLayer）ため、ここに含めると「全レイヤー一括OFF」が
    // 何も変えない項目を数えることになる。
    return mapLayers
      .filter((layer) => !isAxisStudioLayer(layer))
      .map((layer) => {
        // disabledとtitleが別々に同じlayer.id判定を繰り返さないよう、理由の文言と紐付けて
        // 1箇所で決める（無効化理由が増えても1本追加するだけでdisabled/titleの両方に
        // 反映される）。
        // disabledReasonの判定はselectedCandidate基準に揃える——RouteAxisProfileの表示条件
        // （selectedCandidateのみ）とhasDetail（segments取得済み）がズレると、候補選択
        // 直後・segments未取得の間、地図の「ルート」チップは無効化されたままなのに、同時に
        // 表示されるRouteAxisProfileのチップ操作でlayerVisibility.routeがONに変わって
        // しまい、地図チップから直接OFFへ戻せない状態が生じる。
        const disabledReason = layer.id === "route" && !selectedCandidate ? "ルートを生成・選択すると使えます" : null;
        const disabled = disabledReason !== null;
        // タイルの最小ズームを下回っているレイヤーは「ONにしても何も出ない理由」を出す。
        // **判定も配線もここ1箇所**で、レイヤー側は記述子へ最小ズームを宣言するだけでよい。
        const tileZoomTooWide = tileZoomTooWideLayerIds.includes(layer.id);
        // 世代が無いレイヤーもズーム不足と同じ扱いにする——どちらも「ONにしても何も出ない」で、
        // 違うのは理由だけ。
        const tileVersionsGated = tileVersionGatedIds.includes(layer.id);
        const notice =
          tileVersionsGated && tileVersionsFailed
            ? TILE_VERSIONS_MISSING_NOTICE
            : tileZoomTooWide
              ? TILE_ZOOM_TOO_WIDE_NOTICE
              : null;
        const legendDetails =
          legendDetailsByLayerId[layer.id] ??
          staticFilterLegendDetails[layer.id] ??
          layer.readOnlyLegend?.map((block) => ({ ...block, hiddenKeys: NO_HIDDEN_LEGEND_KEYS }));
        // 地図上チップの▶パネル本体には説明文を常時表示せず、凡例のみを表示する。折りたたみ中の
        // 「表示する項目を選ぶ」設定パネル（MapOverlayControls.tsx: renderVisibilitySettings）
        // 側は、各メンバー行に個別の情報アイコンを置き、押したメンバーだけ説明文を表示する
        // （panelHintは推定/観測/動的の全メンバーへ渡すが、常時表示にはしない）。
        // 「動的グループ」の判定はmapLayers.ts側の単一ソースdataNature==="dynamic"を見る
        // （layer.idのハードコード列挙ではなく、この基準に揃えることで新規レイヤーが
        // 増えても追従する）。
        const isDynamicGroupLayer = layer.dataNature === "dynamic";
        return {
          id: layer.id,
          icon: layer.icon,
          label: layer.label,
          chipLabel: layer.chipLabel ?? layer.label,
          notice,
          on: layerVisibility[layer.id],
          disabled,
          // 絞り込みを持たない動的グループには案内を付けない（開いても設定が無い）。
          title: disabledReason ?? (isDynamicGroupLayer ? layer.description : `${layer.description}[設定は▶から]`),
          legendDetails,
          // 地図上チップのカテゴリ束ね（MapOverlayControls.tsx）用。
          category: layer.category,
          dataNature: layer.dataNature,
          axisStudioLayer: layer.axisStudioLayer,
          // 「表示する項目を選ぶ」設定パネルの個別情報アイコン用の説明文。
          panelHint: layer.panelHint,
          // レイヤーのデータ取得状態。LayerChip（サイドバー）と同じくOFF中の抑制は
          // ChipButton自身が`active && dataStatus != null`で行うため、ここでは
          // layerVisibilityで抑制せずそのまま渡す。
          // ソースが1つも作られていないためMapLibreのイベントは何も言わない。
          // 世代待ちは読み込み中、届かないと分かった後はエラーとして見せる。
          dataStatus: tileVersionsGated ? (tileVersionsFailed ? "error" : "loading") : layerDataStatus[layer.id],
        };
      });
  }, [
    selectedCandidate,
    layerVisibility,
    tileZoomTooWideLayerIds,
    tileVersionGatedIds,
    tileVersionsFailed,
    layerDataStatus,
    roadAxisPanels,
    routeLegendDetails,
    staticFilterLegendDetails,
    disasterLegendDetails,
    mapLayers,
  ]);

  // 全レイヤー一括OFF。地図下部中央の時刻スライダー隣に置き、layers/onToggleを既に
  // 持つこちらで扱う。何もONでないときはno-opのため無効化する（誤操作の起点自体を
  // 減らす）。
  const hasAnyLayerOn = overlayLayers.some((layer) => layer.on);
  const handleClearAllLayers = useCallback(() => {
    for (const layer of overlayLayers) {
      if (layer.on) handleLayerToggle(layer.id, false);
    }
  }, [overlayLayers, handleLayerToggle]);

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

  // MapViewからのビューポート通知（MapView.tsx: onViewportChange参照）。
  const handleViewportChange = useCallback((viewport: MapViewport) => {
    setMapViewport(viewport);
  }, []);

  // 今日の見通し（TodayOutlook向け、気象庁MSM予報）・最寄りアメダス実測値（WeatherPanel＝
  // 常設ヘッダー向け）・警告バッジ3種（JMA警報・注意報／WBGT／河川氾濫予報）のフェッチ・
  // 状態管理（useWeatherConditionsが持つ。weather[MSM予報]とamedas[アメダス実測]は
  // 独立フェッチ）。locationReadyになるまで待ち、その後はlocationが変わるたびに
  // 再フェッチする。
  const { weather, weatherLoading, weatherError, amedas, amedasLoading, amedasError, warningBadgeItems } =
    useWeatherConditions(location, locationReady);

  // 動的材料の状態別表現契約の[時刻,向き]のうち「向き」は、風・勾配で単一の共有state
  // （travelBearingDeg、実際の進行方向という1つの概念を表す）を使う。「環境」グループの
  // 勾配gridFill・評価軸としての風/勾配（専用way値配信軸）のいずれもこの1つの値を
  // 共有する。設定UIは地図上のTravelBearingControl（`components/TravelBearingControl/`）
  // 1箇所に集約されている。
  const [travelBearingDeg, setTravelBearingDeg] = useState(0);

  // レンズが全道路の塗りとして有効な間（ルート前、またはルート後も残す設定）。ルート確定後
  // （hasDetail）は、視界内の全道路への一律色分けというこの機能の役割自体を終了し、ルート
  // 自身の実際の進行方向・到達時刻を使う routeStyleModes.ts の routeColorableModeFromAxis へ委ねる
  // （lensKeepAfterRouteがtrueなら周囲の道路も薄く残す）。
  const lensBackgroundShown = !hasDetail || lensKeepAfterRoute;
  // 二次軸rampレイヤーの表示フラグ（キー=axisMapLayerId）。レンズに選ばれたramp軸だけON。
  const axisVisibility = useMemo(
    () =>
      Object.fromEntries(
        axisCatalog.rampAxes.map((axis) => [axisMapLayerId(axis.axisId), lens === axis.axisId && lensBackgroundShown]),
      ),
    [axisCatalog.rampAxes, lens, lensBackgroundShown],
  );
  // 専用way値配信軸（`dedicated_way_value_layer=true`、現状: 風・勾配）のうち、いま
  // フェッチすべき軸。レンズが指している軸（ルート前の全道路一律色分け）だけで、軸ごとの
  // 分岐は持たない。
  const dedicatedFetchAxes = useMemo(() => {
    const lensAxis = axisCatalog.dedicatedAxes.find((axis) => axis.axisId === lens);
    return lensAxis && lensBackgroundShown ? [lensAxis] : [];
  }, [axisCatalog.dedicatedAxes, lens, lensBackgroundShown]);
  // 想定速度（地図上のRideConditionBarの入力、値域の丸めはそちらのclampSpeedKmhが担う）は
  // 走行速度に依存する軸（風）にも効く。時刻・想定速度を実際にリクエストへ載せるかは
  // 軸カタログの宣言（needsTime/needsSpeed）が決めるため、ここでは全軸共通の入力として
  // 渡すだけでよい。
  const dedicatedWayValueResults = useDedicatedWayValues(
    dedicatedFetchAxes,
    mapViewport,
    travelBearingDeg,
    dynamicLayerTargetTime,
    assumedSpeedKmh,
  );
  // レイヤーID（`${axisId}Axis`）→表示フラグ。レンズに選ばれた専用配信軸だけON
  // （axisVisibilityと同じ形。MapViewは軸ごとのpropを持たない）。
  const dedicatedWayValueVisibility = useMemo(
    () =>
      Object.fromEntries(
        axisCatalog.dedicatedAxes.map((axis) => [
          dedicatedWayValueMapLayerId(axis.axisId),
          lens === axis.axisId && lensBackgroundShown,
        ]),
      ),
    [axisCatalog.dedicatedAxes, lens, lensBackgroundShown],
  );
  // MapViewへは軸id→値／軸id→フェッチ進行中の汎用Mapとして渡す
  // （design-principles.md構造仕様3: 軸ごとにpropを新設しない）。MapView側はこれを使い、
  // まだ値を受け取っていないwayを「取得中」（COLOR_LOADING）と「取得済みだが値が無い」
  // （COLOR_NO_DATA）で塗り分ける。
  const dedicatedWayValues = useMemo(
    () => new Map([...dedicatedWayValueResults].map(([axisId, result]) => [axisId, result.values])),
    [dedicatedWayValueResults],
  );
  const dedicatedWayValueLoading = useMemo(
    () => new Map([...dedicatedWayValueResults].map(([axisId, result]) => [axisId, result.loading])),
    [dedicatedWayValueResults],
  );
  // レンズが専用配信軸を指している間だけ、そのフェッチのloading/empty/errorをLensControlの
  // ピルへ渡す（road_surface等の経路[useLayerDataStatus]はこれらのfetchを観測できないため、
  // deriveFetchLayerStatusで動的気象レイヤーと同じ判定を共有する）。ramp軸・総合難易度・
  // なしはこの失敗モードを持たないためundefinedのまま。
  const lensFetchStatus = useMemo<LayerDataStatus | undefined>(() => {
    if (!axisCatalog.dedicatedAxes.some((axis) => axis.axisId === lens)) return undefined;
    if (!lensBackgroundShown) return undefined;
    const result = dedicatedWayValuesFor(dedicatedWayValueResults, lens);
    return deriveFetchLayerStatus(
      result.loading,
      result.error ? "fetch-failed" : null,
      result.values.size > 0,
      result.hasFetched,
    );
  }, [axisCatalog.dedicatedAxes, lens, lensBackgroundShown, dedicatedWayValueResults]);
  // `dedicated_way_value_layer`軸の地図表示宣言（種類・単位・しきい値・段階ラベル、いずれも
  // 軸カタログ由来）を、axisId→宣言の汎用MapとしてMapView・凡例へ配線する。軸ごとの
  // useMemo・propは持たない（design-principles.md構造仕様3）。
  const dedicatedWayValueDisplays = useMemo(() => {
    const map = new Map<string, DedicatedWayValueDisplay>();
    for (const axis of axisCatalog.axes) {
      if (!axis.dedicatedWayValueLayer) continue;
      map.set(axis.axisId, {
        kind: axis.mapValueKind ?? "difficulty",
        unit: axis.mapValueUnit ?? "",
        boundaries: axis.mapValueThresholds ?? undefined,
        bandLabels: axis.displayBandLabelsOverride ?? undefined,
      });
    }
    return map;
  }, [axisCatalog.axes]);

  // レンズの選択肢（公開軸すべて、軸カタログ順）。「未使用」はこの候補を評価した重み
  // （生成後はgeneratedRoutePreference、生成前はライブなroutePreference）で判定し、
  // 「ルート後のみ」はルート前に塗る手段（ramp・専用配信）を持たない軸に付ける。
  const lensOptions = useMemo<LensOption[]>(() => {
    const weights = generatedRoutePreference ?? routePreference;
    const rampAxisIds = new Set(axisCatalog.rampAxes.map((axis) => axis.axisId));
    return axisCatalog.axes.map((axis) => ({
      id: axis.axisId,
      label: axis.label,
      color: axisChipColors[axis.axisId] ?? LENS_NEUTRAL_COLOR,
      description: axis.description,
      unused: (weights[axis.axisId] ?? 0) <= 0,
      routeOnly: !rampAxisIds.has(axis.axisId) && !axis.dedicatedWayValueLayer,
    }));
  }, [axisCatalog.axes, axisCatalog.rampAxes, axisChipColors, generatedRoutePreference, routePreference]);
  // 現在のレンズの凡例。ルート後はルート線のモード凡例、ルート前はramp軸・専用配信の凡例。
  // どちらも塗る手段が無ければ空。段階の表示ON/OFFはどの経路でも効く（ramp軸は
  // staticFilterAxesのfilter、専用配信は色式の透明化、ルート線はモードのfilter）。
  const lensLegend = useMemo<LegendEntry[]>(() => {
    if (lens === LENS_NONE_ID) return [];
    if (hasDetail) return getRouteStyleMode(routeStyleModes, lens).legend;
    const rampAxis = axisCatalog.rampAxes.find((axis) => axis.axisId === lens);
    if (rampAxis) return buildAxisRampLegend(rampAxis);
    const axis = axisCatalog.axes.find((a) => a.axisId === lens);
    if (axis?.dedicatedWayValueLayer) {
      // 専用way値配信軸の段階はfilter述語を持てない（値がfeature-state経由で入る）。
      // 絞り込みは色式側（dedicatedWayValueHiddenBands）が担うため、ここは空のfilterで渡す。
      return dedicatedWayValueLegend(dedicatedWayValueDisplays.get(lens)).map((band) => ({
        ...band,
        filter: [],
      }));
    }
    return [];
  }, [lens, hasDetail, routeStyleModes, axisCatalog.rampAxes, axisCatalog.axes, dedicatedWayValueDisplays]);

  // 専用way値配信軸ごとの非表示段階（ルート確定前の全道路の塗り側の絞り込み）。保存先は
  // ルート線と同じhiddenLegendKeysByMode[軸id]で、段階キーも共通（mapColorLegend.ts:
  // legendBandKey）——ルート生成の前後で同じ段階が隠れたままになる。
  const dedicatedWayValueHiddenBands = useMemo(
    () =>
      new Map(
        axisCatalog.dedicatedAxes.map((axis) => [
          axis.axisId,
          hiddenLegendKeysByMode[axis.axisId] ?? NO_HIDDEN_LEGEND_KEYS,
        ]),
      ),
    [axisCatalog.dedicatedAxes, hiddenLegendKeysByMode],
  );

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
        startTime: dynamicLayerTargetTime,
        startTimePinned: departureTimePinned,
        hardFilters,
        // 軸カタログ未取得のまま軸idを送ると、backendは存在しない軸idを黙って無視する
        // （road_graph_engine.py: AXIS_DEFINITIONS.get(lens_axis_id)、422にはならない）。
        // route_preferenceと同じく、カタログが未確定の間は送らない——選んだ軸で塗られない
        // 事実が手掛かり無しで起きるのを避ける（失敗自体はRouteSettingsPanelが表示する）。
        lensAxisId: axisCatalog.loaded && lens !== LENS_NONE_ID && lens !== LENS_DIFFICULTY_ID ? lens : null,
        // 軸カタログ未取得のままキー整合を行うと静的フォールバック（既存軸）に合わせて
        // 書き換えてしまうため、その場合はroute_preference自体を省略しbackendの既定値
        // （load_route_preference、常に最新のAXIS_DEFINITIONS由来）へ委ねる。
        routePreference:
          weightOverrideEnabled && axisCatalog.loaded
            ? (syncRoutePreferenceKeys(routePreference, axisCatalog.defaultWeights) ?? routePreference)
            : null,
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
      dynamicLayerTargetTime,
      departureTimePinned,
      hardFilters,
      lens,
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

  // 選んだ区間を相手の道へ差し替えた経路を、backendで評価し直して候補一覧へ加える
  // （docs/tasks/T621.md）。frontendは経路の組み立てだけを行い、評価はbackendが
  // 既存候補と同じ経路で行う（構造仕様1・10）。
  // 選んだ組み合わせをbackendで評価する。差分の表示と「作る」で同じものを使い、評価済みなら
  // 投げ直さない。
  async function evaluateSplicedRoute(): Promise<RouteCandidate | null> {
    if (!editingRoute || appliedAlternatives.length === 0 || !splicedShape) return null;
    const cached = splicePreviews[spliceChoiceKey];
    if (cached) return cached;
    // 表示中の候補を作った条件をそのまま使う。いまのフォーム値を使うと、生成後に重みを
    // 変えてから合成したときに、その1本だけ別条件で評価された候補が同じ並びへ入る。
    const generatedInput = generatedConditions?.input;
    if (!generatedInput) return null;
    const { routes: candidates } = await generateRoutes(
      { ...buildGenerateRequest(generatedInput), spliced_edge_ids: splicedShape.edgeIds },
      setGenerationProgress,
    );
    const spliced = candidates[0] ?? null;
    if (spliced) setSplicePreviews((current) => ({ ...current, [spliceChoiceKey]: spliced }));
    return spliced;
  }

  // 作る前に「この組み合わせにすると何がどう変わるか」を見る。評価はbackendでしか出せない
  // （Edgeコストは探索と表示で同じ値を共有する、構造仕様10）ため、押したときだけ投げる。
  async function handlePreviewSplice() {
    if (!editingRoute || appliedAlternatives.length === 0 || previewing) return;
    setPreviewing(true);
    setSpliceError(null);
    try {
      const spliced = await evaluateSplicedRoute();
      if (!spliced) setSpliceError("組み合わせたルートを評価できませんでした");
    } catch (error) {
      setSpliceError(error instanceof Error ? error.message : "組み合わせたルートの評価に失敗しました");
    } finally {
      setPreviewing(false);
      setGenerationProgress(null);
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
    setSplicing(true);
    setErrorMessage(null);
    setSpliceError(null);
    try {
      const spliced = await evaluateSplicedRoute();
      if (!spliced) {
        setSpliceError("組み合わせたルートを評価できませんでした");
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
      setAppliedAlternatives([]);
      setSplicePreviews({});
      setSelectedRouteSegment(null);
      // 同じ場所が結果の一覧へ戻り、作ったルートが選ばれた状態で並ぶ。
      setEditingRouteId(null);
      notifyRouteOutcome();
    } catch (error) {
      setSpliceError(error instanceof Error ? error.message : "組み合わせたルートの評価に失敗しました");
    } finally {
      applyingRef.current = false;
      setSplicing(false);
      setGenerationProgress(null);
    }
  }

  async function handleGenerate(distanceKm: number) {
    setLoading(true);
    setGenerationProgress(null);
    setErrorMessage(null);
    try {
      // 送るpayloadとdirty判定の比較キーを同じ入力から導出する（lib/generationRequest.ts）。
      // 候補数はステッパー（‹/›）操作のみで変更でき、1〜MAX_ROUTES範囲の整数文字列以外には
      // なり得ないため、buildCurrentGenerationInput側でそのままNumber化して使う。
      const generationInput = buildCurrentGenerationInput(distanceKm);
      const {
        routes: candidates,
        conditions,
        engine,
        noCandidatesReason,
      } = await generateRoutes(buildGenerateRequest(generationInput), setGenerationProgress);
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
      setEditingRouteId(null);
      setAppliedAlternatives([]);
      setSplicePreviews({});
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
      });
      setGeneratedRoutePreference(conditions.route_preference);
      if (candidates.length === 0) {
        // バックエンドが原因を特定できた場合はそれを表示する（routeApi.ts:
        // generateRoutes参照）。特定できない場合のみ汎用文言。
        setErrorMessage(
          noCandidatesReason ?? "条件に合うルート候補が見つかりませんでした。距離を変えて試してください。",
        );
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
      const message = error instanceof Error ? error.message : "不明なエラーが発生しました";
      // generateRoutes（routeApi.ts: postJson）自体の失敗は既にそちらでdebugLog記録済みだが、
      // ここに来る他の例外（候補構築中の想定外エラー等）も含め、ルート生成ハンドラの失敗として
      // ここでも記録する（多層防御）。
      debugLog("api:route", "ルート生成ハンドラで例外", { error: message }, "error");
      setErrorMessage(message);
      notifyRouteOutcome();
    } finally {
      setLoading(false);
      setGenerationProgress(null);
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
        {/* 「条件が変更されています」は結果欄の先頭にも出るが、条件を変えている本人は
            設定側を見ている。押すべきボタンの隣でも同じことを知らせる。 */}
        {conditionsDirty && (
          <span
            className={styles.dirtyDot}
            role="img"
            aria-label="条件が変更されています"
            title="条件が変更されています"
          />
        )}
        <Button variant="primary" size="sm" type="button" disabled={loading} onClick={routeFormSubmit.handleSubmit}>
          {loading ? (generationProgressLabel ?? "生成中...") : "ルート生成"}
        </Button>
      </div>
    );
  }

  // 「ルート設定」区分の中身（天候・アプリ名は常設ヘッダにある）。
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
    const failure = routeFormSubmit.error ?? errorMessage;
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
              setEditingRouteId(selectedCandidate.id);
              // 前回の編集セッションの残り（適用済みの乗り換え・失敗の文言）を持ち込まない。
              // 通常は編集を抜けるときに畳まれるが、候補ごと消えて編集面が閉じた場合は
              // 抜ける導線を通らない。
              setAppliedAlternatives([]);
              setSplicePreviews({});
              setSpliceError(null);
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
        {conditionsDirty && <p className={styles.dirtyHint}>条件が変更されています</p>}
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
                  ルート全体の内訳と同じ表示部品）を表示する。地図側のDETAIL_LAYER_ID/
                  DETAIL_HIT_LAYER_IDは選択中候補（selectedCandidate）にしか描画されない
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
                      axisColors={axisChipColors}
                    />
                    {researchEnabled && Object.keys(selectedRouteSegment.segment.material_values).length > 0 && (
                      <ul className={styles.selectedSegmentMaterialValues}>
                        {Object.entries(selectedRouteSegment.segment.material_values).map(([materialId, value]) => (
                          <li key={materialId}>
                            {materialCatalogLabel(materialId, materialCatalog)}:{" "}
                            {formatMaterialValue(materialId, value, materialCatalog)}
                          </li>
                        ))}
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
                    axisColors={axisChipColors}
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
          setEditingRouteId(null);
          setAppliedAlternatives([]);
          setSpliceError(null);
        }}
        appliedCount={appliedAlternatives.length}
        hasAlternatives={spliceStretchFeatures.length > 0}
        onUndo={() => {
          setSpliceError(null);
          setAppliedAlternatives((current) => current.slice(0, -1));
        }}
        onReset={() => {
          setSpliceError(null);
          setAppliedAlternatives([]);
        }}
        preview={splicePreview}
        previewing={previewing}
        onPreview={handlePreviewSplice}
        onApply={handleApplySplice}
        axes={axisCatalog.axes}
        axisColors={axisChipColors}
        error={spliceError}
        applying={splicing}
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
          <WarningBadgeList items={warningBadgeItems} />
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
            （.maplibregl-ctrl-bottom-*、globals.cssのapp-debug-console等と同じマーカークラスの
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
            staticLayerVisibility={layerVisibility}
            dynamicWeather={dynamicWeather}
            dedicatedWayValueVisibility={dedicatedWayValueVisibility}
            dedicatedWayValueHiddenBands={dedicatedWayValueHiddenBands}
            dedicatedAxes={axisCatalog.dedicatedAxes}
            dedicatedWayValues={dedicatedWayValues}
            dedicatedWayValueDisplays={dedicatedWayValueDisplays}
            dedicatedWayValueLoading={dedicatedWayValueLoading}
            axisVisibility={axisVisibility}
            secondaryAxisCasingLayerIds={secondaryAxisCasingLayerIds}
            roadHiddenKeysByMode={debouncedRoadHiddenKeysByMode}
            staticLegendHiddenKeysByAxis={debouncedStaticLegendHiddenKeysByAxis}
            routeLayerOn={layerVisibility.route}
            routeStyleModes={routeStyleModes}
            routeStyleModeId={lens}
            hiddenRouteLegendKeys={hiddenRouteLegendKeys}
            onTileZoomTooWideChange={setTileZoomTooWideLayerIds}
            onViewportChange={handleViewportChange}
            onLayerDataStatusChange={setMapViewLayerDataStatus}
            refreshToken={refreshToken}
            tileVersionsReady={tileVersionsReady}
            // experimentSlots（研究モード中の生成履歴、1件目は常にEXPERIMENT_SLOT_
            // COLORS[0]="#16a34a"=緑）はdrawExperimentSlotsが無条件で描画するため、
            // 実際に「比較」タブを見ているとき以外に地図へ残ると選択中ルートの色分けと
            // 紛らわしい。研究モード中の比較用オーバーレイという役割上、
            // comparisonTabActiveの間だけ渡すよう限定する（スロット自体の記録・
            // ComparisonPanelでの一覧表示は researchEnabled のみで動く）。
            experimentSlots={researchEnabled && comparisonTabActive ? experimentSlots : []}
            rampAxes={axisCatalog.rampAxes}
            axes={axisCatalog.axes}
            axisColors={axisChipColors}
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
            routeFitObscuredPx={routeFitObscuredPx}
          />

          <LensControl
            lens={lens}
            onLensChange={handleLensChange}
            axisOptions={lensOptions}
            legend={lensLegend}
            hiddenLegendKeys={hiddenRouteLegendKeys}
            onToggleLegendKey={handleRouteLegendToggle}
            onSetHiddenLegendKeys={handleLensLegendSetHidden}
            keepAfterRoute={lensKeepAfterRoute}
            onKeepAfterRouteChange={setLensKeepAfterRoute}
            hasDetail={hasDetail}
            dataStatus={lensFetchStatus}
          />

          <MapOverlayControls
            layers={overlayLayers}
            onToggle={handleLayerToggle}
            onLegendEntryToggle={toggleHiddenLegendKey}
            onLegendAxisSetHidden={setHiddenLegendKeysForAxis}
          />

          {/* 地図下部中央の行。「まとめて元に戻す」操作を並べる（design-principles.md
              「UI仕様」: 地図の視界を圧迫しない）。レイヤーのON/OFFと凡例の絞り込みは
              別の状態のため、戻す操作も別々に要る。 */}
          <div ref={bottomControlRowRef} className={styles.bottomControlRow}>
            <button
              type="button"
              onClick={handleClearAllLayers}
              disabled={!hasAnyLayerOn}
              aria-label="表示中のレイヤーをすべて非表示にする"
              title="表示中のレイヤーをすべて非表示にする"
              className={styles.clearAllButton}
            >
              <ClearAllLayersIcon size={14} />
            </button>
            <button
              type="button"
              onClick={handleClearAllFilters}
              disabled={!hasHiddenFilters}
              aria-label="絞り込みをすべて解除する"
              title="絞り込みをすべて解除する"
              className={styles.clearAllButton}
            >
              <ClearAllFiltersIcon size={14} />
            </button>
            {/* このページが持つ地図インスタンスだけを描き直す（refreshToken）。押した人の
                画面にしか影響しない純粋なクライアント操作で、サーバー側のタイルキャッシュには
                触れない（そちらは全利用者へ影響するため/adminのTileCachePanelにある）。
                ページ全体を再読み込みすると生成済みのルート候補が消えるため、地図だけを
                描き直す入口をここへ残す。 */}
            <button
              type="button"
              onClick={() => setRefreshToken((v) => v + 1)}
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
              （dynamicLayerTargetTime）。 */}
          <div className={styles.rideConditionColumn}>
            <RideConditionBar
              departureTime={dynamicLayerTargetTime}
              onDepartureTimeChange={setDynamicLayerTargetTime}
              onDepartureNow={handleDynamicLayerNow}
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
              aria-pressed={mobileSheet === "routeSettings"}
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
              aria-pressed={mobileSheet === "routeOutcome"}
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
