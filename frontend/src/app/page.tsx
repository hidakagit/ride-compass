"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as RadioGroup from "@radix-ui/react-radio-group";
import Disclosure from "@/components/Disclosure/Disclosure";
import { Card } from "@/components/ui/Card/Card";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { Button } from "@/components/ui/Button/Button";
import MapView from "@/components/Map/MapView";
import LocationControl from "@/components/LocationControl/LocationControl";
import MapOverlayControls, { type OverlayLayerChip } from "@/components/MapOverlayControls/MapOverlayControls";
import {
  ClearAllLayersIcon,
  LogIcon,
  MapAppearanceIcon,
  RouteIcon,
  RouteSettingsIcon,
} from "@/components/Map/icons";
import MapLayersPanel from "@/components/MapLayersPanel/MapLayersPanel";
import BottomSheet, { clampSheetHeightVh, DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import {
  buildMapLayers,
  buildRoadSurfaceSharedLayerIds,
  type LayerDataStatusByLayer,
  type MapLayerId,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import { RAMP_AXES, axisMapLayerId } from "@/components/Map/axisLayers";
import { primaryAttributeIdsToLayerIds } from "@/components/Map/primaryAttributes";
import { summarizeLegendFilters, type LegendFilterSummaryAxis } from "@/components/Map/legendFilter";
import {
  ROAD_FILTER_AXES,
  ROAD_LINE_COLOR_AXIS_ID,
  ROAD_LINE_WIDTH_AXIS_ID,
  getRoadFilterAxis,
  type RoadFilterAxisId,
} from "@/components/Map/roadFilterAxes";
import { buildStaticFilterAxes, type StaticFilterAxisId } from "@/components/Map/staticAttributeLayers";
import {
  DEFAULT_ROUTE_STYLE_MODE_ID,
  ROUTE_STYLE_MODES,
  getRouteStyleMode,
  isRouteStyleModeId,
  type RouteStyleModeId,
} from "@/components/Map/routeStyleModes";
import LayerChip from "@/components/Map/LayerChip";
// 「生成したルートの色分け」セクション（改善計画: 地図の見え方パネルのグルーピングを
// 地図上チップと統一）で使うモード選択・凡例チェックボックスの見た目は、MapLayersPanel側の
// 既存スタイルをそのまま再利用する（CSS Modulesはクラス名の対訳表を返すだけのため、
// 別コンポーネントからのimportでも問題なく使える。同じ見た目のUIをここだけのために
// 複製しない）。
import layerPanelStyles from "@/components/MapLayersPanel/MapLayersPanel.module.css";
import ErrorText from "@/components/ErrorText/ErrorText";
import RouteForm, { type DestinationButtonState, type RouteMode } from "@/components/RouteForm/RouteForm";
import RouteSettingsPanel, { DEFAULT_HARD_FILTERS } from "@/components/RouteSettingsPanel/RouteSettingsPanel";
import RouteList from "@/components/RouteList/RouteList";
import WeatherPanel from "@/components/WeatherPanel/WeatherPanel";
import WarningBadgeList, { type WarningBadgeItem } from "@/components/WarningBadge/WarningBadge";
import DynamicLayerTimeSlider, {
  type DynamicLayerTimeSliderFrame,
} from "@/components/DynamicLayerTimeSlider/DynamicLayerTimeSlider";
import {
  fetchNowcastFrames,
  precipitationFrames,
  precipitationRenderPayload,
  trimToCurrentAndFuture,
  PRECIPITATION_INTENSITY_LEVELS,
  type NowcastFrame,
} from "@/components/Map/precipitationNowcast";
import { windFrames, windRenderPayload, WIND_SPEED_LEGEND_LEVELS, type MapViewport } from "@/components/Map/windLayer";
import {
  fetchThunderNowcastFrames,
  thunderFrames,
  thunderRenderPayload,
  tornadoRenderPayload,
  THUNDER_ACTIVITY_LEVELS,
  TORNADO_POTENTIAL_LEVELS,
  type ThunderNowcastFrame,
} from "@/components/Map/thunderNowcast";
import {
  formatDynamicFrameHourMinute,
  formatDynamicFrameMinuteOnly,
  formatDynamicFrameTime,
  frameIndexForTime,
  mergeFrameTimes,
  nearestTimeIndex,
} from "@/components/Map/dynamicWeather";
import { useWeatherGrid } from "@/hooks/useWeatherGrid";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { syncRoutePreferenceKeys } from "@/lib/routePreferenceSync";
// 改善計画T270: WeightPanel自体（編集UI）は/adminへ移設したが、既定値定数は
// useStoredJsonStateの初期値としてこのページでも使う。
import { DEFAULT_ROUTE_PREFERENCE, DEFAULT_SCORING_WEIGHTS } from "@/components/WeightPanel/WeightPanel";
import ComparisonPanel from "@/components/ComparisonPanel/ComparisonPanel";
import DebugConsole from "@/components/DebugConsole/DebugConsole";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { debugLog } from "@/lib/debugLog";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useLocation } from "@/hooks/useLocation";
import { useStoredState, useStoredJsonState } from "@/hooks/useStoredState";
import { generateRoutes } from "@/services/routeApi";
import { getCurrentWeather, getFloodForecasts, getWbgtStatus, getWeatherWarnings } from "@/services/weatherApi";
import type {
  Coordinates,
  HardFilterOverride,
  RouteCandidate,
  RoutePreferenceWeights,
  ScoringWeights,
} from "@/types/route";
import type { FloodForecasts, WbgtStatus, WeatherConditions, WeatherWarnings } from "@/types/weather";
import { EXPERIMENT_SLOT_COLORS, MAX_EXPERIMENT_SLOTS, type ExperimentSlot } from "@/types/experimentSlot";
import styles from "./page.module.css";

const DISTANCE_TOLERANCE_KM = 5;

// backend/app/api/routers/routes.pyのRouteGenerateRequest.distance_km（Field(gt=0, le=100)）と
// 一致させる（目的地モードの自動算出値もこの上限でクランプする、handleGenerate参照）。
const MAX_DISTANCE_KM = 100;

// 改善計画T365-2: 目的地モードでは距離をユーザーに入力させず、地図上の経由地・目的地から
// 自動算出する（backend/app/domain/geo.py: haversine_distance_kmと同じ球面距離の簡易実装。
// フロントは既存の距離計算ユーティリティを持たないためここに最小実装する）。
function haversineKm(a: Coordinates, b: Coordinates): number {
  const EARTH_RADIUS_KM = 6371;
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(b.latitude - a.latitude);
  const dLon = toRad(b.longitude - a.longitude);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.latitude)) * Math.cos(toRad(b.latitude)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(h));
}

// 凡例の絞り込みチェックを地図へ反映するまでの猶予。チェック自体は即時反映が原則
// （T31）だが、連続タップのたびにMapLibreのフィルタ再適用を走らせない（useDebouncedValue参照）。
// 道路情報の2軸に加え、改善計画T63で車ストレス・指定路線・停止要因POI・
// 事故（当事者/重大度）の絞り込みにも同じ猶予を適用する。
const LEGEND_FILTER_DEBOUNCE_MS = 400;

// 色分けモード（ルート）の保存先。プライベートブラウジング等でlocalStorageが
// 使えない環境があるため、読み書きとも失敗はデフォルトモードへのフォールバックとして
// 握りつぶす。路面側は色分けモードを持たない（常に固定色。roadFilterAxes.ts参照）ため
// 対応する保存先は無い。
const ROUTE_STYLE_MODE_STORAGE_KEY = "ridecompass:route-style-mode";

// 「地図の見え方」（系統B）の設定はすべてlocalStorageへ保存し、リロード後も復元する
// （保存ポリシー統一、T32。以前は色分けモードだけが保存され、レイヤーON/OFF・絞り込みは
// リロードで消えていた）。生成条件（系統A: 出発地点・距離・重み）は保存しない方針
// （毎回現在地・既定値から始める）。
const LAYER_VISIBILITY_STORAGE_KEY = "ridecompass:layer-visibility";
const HIDDEN_LEGEND_KEYS_STORAGE_KEY = "ridecompass:hidden-legend-keys";
const GENERATE_OPEN_STORAGE_KEY = "ridecompass:generate-open";
// モバイル下部シート（「ルートを作る」/「地図の見え方」）の高さ。2シートは排他表示のため
// 1つの値を共有する（BottomSheetのheightVh props参照）。
const MOBILE_SHEET_HEIGHT_STORAGE_KEY = "ridecompass:mobile-sheet-height-vh";

// ramp軸（軸スタジオで増減しうる動的レイヤー）を除いた、ビルド時から固定のレイヤー集合の
// 既定値。DEFAULT_LAYER_VISIBILITY（静的フォールバック全体）と、useStoredStateの
// deserialize（下記）がaxisCatalog.loaded===true時に組み立てる「実行時カタログ由来の
// キー集合」の両方が、この固定部分を共通の土台として使う。
const FIXED_LAYER_VISIBILITY_DEFAULTS: Omit<MapLayerVisibility, `axis:${string}`> = {
  elevation: false,
  // 改善計画T165: 「道路情報」（road）を論理2レイヤーへ分割。旧保存値（road: boolean）から
  // 両方へ移行する処理はuseStoredStateのdeserialize（下記）参照。
  roadType: false,
  roadSurface: false,
  designation: false,
  tunnel: false,
  oneway: false,
  stopPoi: false,
  supplyPoi: false,
  accidents: false,
  // 改善計画T171: 降水ナウキャスト。初期表示から地図を覆うと視界を圧迫するため既定OFF
  // （設計原則12、他の静的レイヤーと同じ「明示的にONにして初めて出る」規約）。
  precipitationNowcast: false,
  // 改善計画T178: 風の矢印。precipitationNowcastと同じ理由で既定OFF。
  windVector: false,
  // 改善計画T204: 雷ナウキャスト・竜巻発生確度ナウキャスト。同じ理由で既定OFF。
  thunderNowcast: false,
  tornadoNowcast: false,
  route: true,
};

const DEFAULT_LAYER_VISIBILITY: MapLayerVisibility = {
  ...FIXED_LAYER_VISIBILITY_DEFAULTS,
  // 二次軸rampレイヤー（改善計画T145b）。backendレジストリ生成物（axis-catalog.json）の
  // kind="ramp"軸から自動生成されるため、個別の行を手書きせずカタログから導出する
  // （新しい軸が増えてもこのファイルの編集は不要）。既定はすべてOFF。
  // これは実行時カタログ未取得時の静的フォールバック（RAMP_AXES＝axisLayers.tsのビルド時
  // スナップショット）であり、軸スタジオで新規公開された軸のキーはここには含まれない
  // （フェッチ完了後の扱いはuseStoredStateのdeserialize、下記参照）。
  ...Object.fromEntries(RAMP_AXES.map((axis) => [axisMapLayerId(axis.axisId), false])),
};

// 「どのモードでも非表示カテゴリ無し」を表す共通の空配列。useStateの外に置いて参照を
// 固定し、MapView側のエフェクト依存（hidden*LegendKeys）が毎レンダーで発火しないようにする。
const NO_HIDDEN_LEGEND_KEYS: string[] = [];

// 降水ナウキャスト・風の凡例（実機フィードバック「風と雨の凡例も欲しい」）。地図チップの
// ▶パネル（MapOverlayControls: renderLegendDetails）は表示専用でLegendEntry.filterを
// 実際には適用しない（道路種別等のようなカテゴリ絞り込みができるレイヤーではないため）ため、
// filterは一致することのないダミー値にしている。色・階級の実データはprecipitationNowcast.ts/
// windLayer.ts側（実際の描画・凡例双方の単一の情報源）から持ってくる。他レイヤーと違い
// 絞り込み状態を持たないため、useMemoではなくモジュール直下の固定値でよい。
const UNUSED_LEGEND_FILTER: unknown[] = ["==", 1, 0];
const PRECIPITATION_LEGEND_DETAILS: LegendFilterSummaryAxis[] = [
  {
    label: "",
    legend: PRECIPITATION_INTENSITY_LEVELS.map((level) => ({ ...level, filter: UNUSED_LEGEND_FILTER })),
    hiddenKeys: NO_HIDDEN_LEGEND_KEYS,
  },
];
const WIND_LEGEND_DETAILS: LegendFilterSummaryAxis[] = [
  {
    label: "",
    legend: WIND_SPEED_LEGEND_LEVELS.map((level) => ({ ...level, filter: UNUSED_LEGEND_FILTER })),
    hiddenKeys: NO_HIDDEN_LEGEND_KEYS,
  },
];
// 雷・竜巻の凡例（改善計画T204）。precipitation/wind凡例と同じパターン（表示専用、
// filterはダミー値）。実データ（活動度・発生確度のラベル・近似色）はthunderNowcast.ts
// （単一の情報源）から持ってくる。
const THUNDER_LEGEND_DETAILS: LegendFilterSummaryAxis[] = [
  {
    label: "",
    legend: THUNDER_ACTIVITY_LEVELS.map((level) => ({ ...level, filter: UNUSED_LEGEND_FILTER })),
    hiddenKeys: NO_HIDDEN_LEGEND_KEYS,
  },
];
const TORNADO_LEGEND_DETAILS: LegendFilterSummaryAxis[] = [
  {
    label: "",
    legend: TORNADO_POTENTIAL_LEVELS.map((level) => ({ ...level, filter: UNUSED_LEGEND_FILTER })),
    hiddenKeys: NO_HIDDEN_LEGEND_KEYS,
  },
];

// 「ルートを作る」セクション見出しのDOM id。デスクトップの<summary>専用
// （改善計画T300: モバイルは「ルート設定」「ルート結果」の2タブへ分割したため、
// 専用のROUTE_SETTINGS_SHEET_TITLE_ID/ROUTE_OUTCOME_SHEET_TITLE_IDを別途持つ）。
const GENERATE_SECTION_TITLE_ID = "generate-section-title";
// モバイルの「地図の見え方」シート見出しのDOM id。
const MAP_SETTINGS_SHEET_TITLE_ID = "map-settings-sheet-title";
// モバイルの「ルート設定」「ルート結果」シート見出しのDOM id（改善計画T300、
// 「ルート詳細」タブの2分割に伴い新設。旧DEVELOPER_SHEET_TITLE_IDは「開発者」タブ廃止に
// 伴い削除——地図データ再読み込みは地図の見え方タブへ、デバッグログはヘッダーアイコンへ
// それぞれ移設した）。
const ROUTE_SETTINGS_SHEET_TITLE_ID = "route-settings-sheet-title";
const ROUTE_OUTCOME_SHEET_TITLE_ID = "route-outcome-sheet-title";

type MobileSheet = "routeSettings" | "routeOutcome" | "map" | null;

export default function Home() {
  const { location, locationSource, locationReady, locating, locateError, handleLocateMe } = useLocation();
  // 改善計画T308: 軸カタログ（ramp表示・凡例チップグルーピングを含む）を先頭で取得する。
  // axisVisibility/secondaryAxisCasingLayerIds（下記）・地図チップ組み立てが参照するため、
  // それらより前で宣言する必要がある。取得完了までとエラー時は静的フォールバック
  // （axisLayers.ts: RAMP_AXES等）を返すため、呼び出し側は常に何かしらの一覧を受け取れる。
  const axisCatalog = useAxisCatalog();

  const [routes, setRoutes] = useState<RouteCandidate[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // 改善計画T364: 地図クリックで指定する経由地（起点→経由地1→...→起点の順で通過する
  // 単一経路を生成する）。指定があれば8方位探索は行わない（handleGenerate参照）。
  const [waypoints, setWaypoints] = useState<Coordinates[]>([]);
  const handleWaypointAdd = useCallback((point: Coordinates) => {
    setWaypoints((prev) => [...prev, point]);
  }, []);
  const handleWaypointRemove = useCallback((index: number) => {
    setWaypoints((prev) => prev.filter((_, i) => i !== index));
  }, []);
  const handleWaypointsClear = useCallback(() => setWaypoints([]), []);

  // 改善計画T365: 目的地（最大1点）。指定時は起点に戻らず目的地で終わる片道ルートになる
  // （handleGenerate参照）。destinationArmedは「目的地を設定」ボタン押下から次の1タップ
  // までの間だけtrueになり、地図クリックが目的地配置として扱われる（MapView.tsx参照）。
  const [destination, setDestination] = useState<Coordinates | null>(null);
  const [destinationArmed, setDestinationArmed] = useState(false);

  // 改善計画T365-2: 周回（距離指定、従来の8方位探索）/目的地（地図タップで経由地・目的地を
  // 指定）モードの切り替え。実機フィードバック「経由地・目的地の操作パネルが地図上で邪魔」を
  // 受け、地図上の浮動パネルを廃止しRouteForm（距離入力・生成ボタンと同じ場所）へ統合した。
  // モード切り替え自体は経由地・目的地の値を消さない（周回モードへ切り替えても地図上のピンは
  // 保持し、目的地モードへ戻れば復元される。地図への表示・追加受付だけがモードで変わる、
  // handleGenerate/MapView.tsxのpinPlacementEnabled参照）。
  const [routeMode, setRouteMode] = useState<RouteMode>("loop");
  const handleRouteModeChange = useCallback((mode: RouteMode) => {
    setRouteMode(mode);
    // 武装中に周回モードへ切り替えた場合、目的地モードへ戻るまで武装状態を持ち越さない。
    setDestinationArmed(false);
  }, []);

  const handleDestinationSet = useCallback((point: Coordinates) => {
    setDestination(point);
    setDestinationArmed(false);
  }, []);
  const handleDestinationClear = useCallback(() => setDestination(null), []);
  // ボタン1個で「未設定→武装→設定済み→解除」を一巡させる（実機フィードバック「アイコンだけに
  // して」を受け、武装中に同じボタンを押すとキャンセルできるようにした、以前はキャンセル手段が
  // 無かった）。
  const handleDestinationButtonClick = useCallback(() => {
    if (destinationArmed) {
      setDestinationArmed(false);
    } else if (destination) {
      setDestination(null);
    } else {
      setDestinationArmed(true);
    }
  }, [destinationArmed, destination]);
  const destinationState: DestinationButtonState = destinationArmed ? "armed" : destination ? "set" : "unset";

  // 距離入力（文字列のまま保持）。RouteForm内ではなくここで持つのは、表示中の候補を
  // 生成したときの条件と現在のフォーム値を比較して「条件が変更されています」ヒントを
  // 出すため（生成条件系の反映タイミング可視化、T31）。
  const [distanceInput, setDistanceInput] = useState("30");
  // 表示中の候補を生成したときの条件スナップショット。重みは値の組をJSON文字列で比較する
  // （フィールド比較の列挙より差分検知の漏れが出にくい）。
  const [generatedConditions, setGeneratedConditions] = useState<{
    latitude: number;
    longitude: number;
    distanceKm: number;
    weightsKey: string;
    // 改善計画T365-2: 目的地モードで生成した場合はdistanceKmが地図上のピンからの
    // 自動算出値になり、distanceInput（RouteFormが表示しない値）とは無関係になるため、
    // conditionsDirtyの距離比較はloopモードで生成したときだけ行う。
    routeMode: RouteMode;
  } | null>(null);

  // 改善計画T365: 生成済みのルート結果（候補一覧・地図描画・選択状態）だけをリセットする。
  // 経由地・目的地のピンは対象外（別々の「クリア」操作として使い分けられるようにする）。
  const handleRoutesClear = useCallback(() => {
    setRoutes([]);
    setSelectedRouteId(null);
    setGeneratedConditions(null);
  }, []);

  // 評価重みのリクエスト上書き（研究インターフェース改善 §10-1/4）。overrideEnabled=falseの間は
  // 生成リクエストからscoring_weights/route_preferenceを省略し、既存挙動（YAML既定値）を
  // 完全に維持する（一般ユーザーには影響しない）。route_preference/routePreference自体は
  // 改善計画T267で一般向けルート設定画面（RouteSettingsPanel）とも共有する状態になった
  // （withAutoEnableにより、どちらのパネルを操作してもこのフラグが自動でONになる）。
  // 改善計画T270: 編集UI（WeightPanel）は/adminへ移設したため、localStorage経由で
  // 共有する（useStoredJsonState）。本ページはこの値を読んでリクエスト構築に使うのみ。
  const [weightOverrideEnabled, setWeightOverrideEnabled] = useStoredJsonState(
    "ridecompass:weight-override-enabled",
    false
  );
  // setter未使用: scoringWeightsの編集UI（WeightPanel）は/adminへ移設済み。このページは
  // 値を読んでリクエスト構築に使うのみ（useStoredJsonStateの戻り値2番目は/admin側が使う）。
  const [scoringWeights] = useStoredJsonState<ScoringWeights>("ridecompass:scoring-weights", DEFAULT_SCORING_WEIGHTS);
  const [routePreference, setRoutePreference] = useStoredJsonState<RoutePreferenceWeights>(
    "ridecompass:route-preference",
    DEFAULT_ROUTE_PREFERENCE
  );
  // 0次ハードフィルタ（改善計画T266・T267）。一般向けルート設定画面（RouteSettingsPanel）が
  // 常時操作するため、weightOverrideEnabledのような別トグルは持たず常にリクエストへ含める
  // （既定値はDEFAULT_HARD_FILTERS＝backendのDEFAULT_HARD_FILTERSと同じ全フィルタ有効で、
  // 省略時と挙動が一致するため常時送信して問題ない）。
  const [hardFilters, setHardFilters] = useState<HardFilterOverride>(DEFAULT_HARD_FILTERS);

  // 実験スロット（研究インターフェース改善 §10-3）: デバッグモード中の生成結果を条件付きで
  // 直近MAX_EXPERIMENT_SLOTS件だけメモリ内に保持し、地図重ね描き・比較表に使う。
  const [experimentSlots, setExperimentSlots] = useState<ExperimentSlot[]>([]);
  const [weather, setWeather] = useState<WeatherConditions | null>(null);
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [weatherError, setWeatherError] = useState<string | null>(null);

  // 警報・注意報バッジ（改善計画T205）。天候と同じ地点変更起点で取得するが、失敗時は
  // バックエンド契約どおり「警報なし」（空配列）として扱うため、weatherErrorと違い
  // エラー表示用のstateは持たない（通信エラー自体はDebugConsoleのcategory
  // "api:weatherWarnings"で追える）。
  const [weatherWarnings, setWeatherWarnings] = useState<WeatherWarnings | null>(null);

  // WBGT警告バッジ（改善計画T174）。警報・注意報バッジと同じ理由・同じstate設計
  // （エラー表示state無し、失敗時はbackend契約どおりlevel=nullとして扱う）。
  const [wbgtStatus, setWbgtStatus] = useState<WbgtStatus | null>(null);

  // 河川氾濫予報バッジ（改善計画T212）。警報・注意報バッジと同じ理由・同じstate設計。
  const [floodForecasts, setFloodForecasts] = useState<FloodForecasts | null>(null);

  // 動的気象レイヤー（降水ナウキャスト・風）が指す対象時刻（T183再設計、実機フィードバック
  // 「時間経過はスライドバー1本で表現する」）。ONの全レイヤーのフレーム時刻を統合した
  // 1本のタイムライン（dynamicWeather.ts: mergeFrameTimes）上の1点で、各レイヤーはこの
  // 時刻に対応する自分のフレームを描画する（下のdynamicWeather memo参照。選択時刻がその
  // レイヤーのデータ範囲外なら描画しない）。
  const [dynamicLayerTargetTime, setDynamicLayerTargetTime] = useState(() => new Date());

  // 降水ナウキャストの時刻一覧（改善計画T170/T171）。フェッチ・更新間隔は
  // layerVisibility.precipitationNowcastがONの間だけ動かすeffect（下記）が管理する。
  // スライダー位置(index)はnowcastFrames自体ではなく共有のdynamicLayerTargetTimeから
  // 都度導出する（下のsliderIndex参照）ため、ここでは持たない。
  const [nowcastFrames, setNowcastFrames] = useState<NowcastFrame[]>([]);
  const [nowcastLoading, setNowcastLoading] = useState(false);
  const [nowcastError, setNowcastError] = useState<string | null>(null);

  // 雷・竜巻の時刻一覧（改善計画T204）。雷ナウキャストと竜巻発生確度ナウキャストは同じ
  // targetTimes_N3.json由来のため、両トグルのどちらか一方でもONの間だけ1本のfetchで
  // 両方をカバーする（nowcastFramesと同じ理由・同じパターン）。
  const [thunderNowcastFrames, setThunderNowcastFrames] = useState<ThunderNowcastFrame[]>([]);
  const [thunderNowcastLoading, setThunderNowcastLoading] = useState(false);
  const [thunderNowcastError, setThunderNowcastError] = useState<string | null>(null);

  // 風・延長降水予報（T183）が共有する格子点マップの取得結果はuseWeatherGrid（下記）が
  // 管理する。スライダー位置はdynamicLayerTargetTimeから導出するため、ここでは持たない。
  // MapViewから伝わる現在のビューポート（改善計画T180、MapView.tsx: onViewportChange参照）。
  // moveend/zoomendのたびに素の値が来るため、フェッチ用にはデバウンスして使う
  // （下のwindDetailフェッチeffect参照）。
  const [mapViewport, setMapViewport] = useState<MapViewport | null>(null);

  // 地図レイヤーのON/OFF（MAP_LAYERSのid単位。レイヤーを追加したらDEFAULT_LAYER_VISIBILITYへ
  // 初期値を1つ足す）。localStorageへの保存・復元はuseStoredState（改善計画T47 R-6）参照。
  // 既知のレイヤーIDかつboolean値のものだけ採用する（レイヤーの増減や壊れた保存値があっても、
  // 残りの設定は活かしてデフォルトで埋める）。
  //
  // 実バグ修正（デッドコード監査、2026-08-25）: 以前はdeserializeが常にDEFAULT_LAYER_VISIBILITY
  // （ビルド時静的7軸ぶんのramp軸キーのみ）を走査してホワイトリストにしていたため、軸スタジオで
  // 新規公開された軸（axis:xxx等）のON/OFF保存値が復元時に黙って捨てられていた
  // （axisVisibility側は既にaxisCatalog.rampAxesベースへ移行済みで非対称だった）。
  // axisCatalog.loadedを見て、未フェッチ時はビルド時静的軸集合（DEFAULT_LAYER_VISIBILITY）、
  // フェッチ完了後は実行時カタログ（axisCatalog.rampAxes）ベースのキー集合を走査するよう
  // 修正。reloadKeyにaxisCatalog.loadedを渡すことで、マウント直後（静的集合で復元）→
  // フェッチ完了後（実行時集合で再復元）の2段階復元にしている（useStoredState.ts参照）。
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
        const next: MapLayerVisibility = axisCatalog.loaded
          ? {
              ...FIXED_LAYER_VISIBILITY_DEFAULTS,
              ...Object.fromEntries(axisCatalog.rampAxes.map((axis) => [axisMapLayerId(axis.axisId), false])),
            }
          : { ...DEFAULT_LAYER_VISIBILITY };
        const parsedRecord = parsed as Record<string, unknown>;
        // 改善計画T165: 「道路情報」（road）の論理分割（roadType/roadSurface）に伴う旧保存値の
        // 移行。旧形式（road: boolean、新キーが無い）が残っていれば両方の新キーへ引き継ぐ
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
        return next;
      },
    },
  );
  // 二次軸rampレイヤー（改善計画T145b）の表示フラグをMapViewへ渡す形（キー=axisMapLayerId）へ
  // 絞り込む。layerVisibility全体を渡さないのは、MapView側のエフェクト依存を軸レイヤー分に
  // 限定するため（deserializeがaxisCatalog.rampAxes（フェッチ完了後）またはDEFAULT_LAYER_
  // VISIBILITY（フェッチ完了前の静的フォールバック）のキー走査で復元するため、軸スタジオ
  // 公開軸を含むaxis:*のキーも既知のレイヤーIDとして保存・復元の対象に自動で含まれる）。
  const axisVisibility = useMemo(
    () =>
      Object.fromEntries(
        axisCatalog.rampAxes.map((axis) => {
          const id = axisMapLayerId(axis.axisId);
          return [id, layerVisibility[id] ?? false];
        }),
      ),
    [layerVisibility, axisCatalog.rampAxes],
  );
  // 改善計画（2次の下敷きの副作用対応）: 2次（車の圧迫感・ramp軸）を太く半透明な下敷きに
  // するのは、その材料（1次、primaryAttributeIdsToLayerIds）が1つでも同時に表示されている
  // ときだけにする。材料が1つも表示されていなければ、下に隠すものが無いため通常の太さ・
  // 不透明度で表示する（以前は2次をONにした瞬間から常に太く半透明にしていたため、道路網が
  // 密な都市部で下敷きの重なりだけで地図全体がぼやけて見える不具合があった、実機
  // フィードバック）。改善計画T308: 軸→一次属性の解決自体はaxisCatalog.secondaryAxes
  // （実行時カタログ、GUI作成軸を含む）のprimaryAttributeIdsへ移した（以前は
  // axisMaterialLayerIds(axisId)がビルド時静的axis-catalog.jsonを軸id経由で逆引きしていた）。
  const secondaryAxisCasingLayerIds = useMemo(
    () =>
      axisCatalog.secondaryAxes.filter((axis) => {
        if (!axis.layerId) return false;
        return primaryAttributeIdsToLayerIds(axis.primaryAttributeIds).some((materialId) => layerVisibility[materialId]);
      }).map((axis) => axis.layerId as MapLayerId),
    [layerVisibility, axisCatalog.secondaryAxes],
  );
  // 色分けモード（ルート）。保存形式はJSON化しない生文字列（他の設定と異なる。
  // isRouteStyleModeIdによる妥当性検証がJSON.parseを兼ねる）。
  const [routeStyleModeId, setRouteStyleModeId] = useStoredState<RouteStyleModeId>(
    ROUTE_STYLE_MODE_STORAGE_KEY,
    DEFAULT_ROUTE_STYLE_MODE_ID,
    { serialize: (v) => v, deserialize: (raw) => (isRouteStyleModeId(raw) ? raw : null) },
  );
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
  // モバイルはBottomSheetの開閉自体がこれに相当するため参照しない（モバイル実機
  // フィードバック対応T34）。
  const [generateOpen, setGenerateOpen] = useStoredState(GENERATE_OPEN_STORAGE_KEY, true, {
    serialize: (v) => JSON.stringify(v),
    deserialize: (raw) => {
      try {
        const parsed = JSON.parse(raw);
        return typeof parsed === "boolean" ? parsed : null;
      } catch {
        return null;
      }
    },
  });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  // モバイルで開いている下部シート（「ルートを作る」/「地図の見え方」の排他表示、または
  // どちらも閉じたnull＝地図全面表示）。デスクトップでは使わない。
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
  const [regionZoomTooWide, setRegionZoomTooWide] = useState(false);
  // レイヤーごとのデータ取得状態（改善計画T87）。MapViewが実際のタイル取得結果
  // （sourcedata/sourcedataloading/errorイベント）から算出し、サイドバー（MapLayersPanel）へ
  // 「読込中」「データなし」「取得失敗」の表示として反映する。
  const [layerDataStatus, setLayerDataStatus] = useState<LayerDataStatusByLayer>({});
  const [refreshToken, setRefreshToken] = useState(0);

  // 改善計画T270でDebugPanel（デバッグモードON/OFFの設定）・SystemStatusPanel・
  // BackendStatus（バックエンド集計情報、地図に依存しない）は/adminへ移設したが、
  // DebugConsole（地図の表示イベント・API呼び出しのライブログ）は地図インスタンスに
  // 紐づく情報のため、レビュー指摘（/adminには地図が無くログがタブ間で共有されない
  // ため実質機能しなくなっていた）を受けてこのページへ戻した（2026-08-24）。
  // 「/admin=設定・集計」「/=地図を操作しながら見るライブログ」という役割分担にする。
  // デバッグモードのON/OFF自体（useDebugEnabled、researchMode.tsと同型のlocalStorage
  // 共有フラグ）は引き続き/adminのDebugPanelで切り替える。
  const debugEnabled = useDebugEnabled();
  const [debugConsoleOpen, setDebugConsoleOpen] = useState(false);
  const researchEnabled = useResearchEnabled();
  // 改善計画T303: RouteSettingsPanelのroute_preferenceキー整合自己修復（T269・T302）は
  // そのパネルがマウントされたときにしか走らない。モバイルでは生成ボタンがヘッダーへ
  // 分離済み（T250）のため「ルート設定」タブを一度も開かずに生成できてしまい、
  // 稀にキー不整合のまま送信して422になりうる。ここでもカタログ（axisCatalog、
  // コンポーネント先頭で取得済み）を使い、生成リクエスト組み立て時（handleGenerate）に
  // 同じ整合チェックを適用する（syncRoutePreferenceKeys、RouteSettingsPanel.tsxと共有）。
  // routePreference state自体は書き換えない（送信直前の値だけを補正する、常時同期化は
  // スコープ外）。

  const selectedCandidate = routes.find((r) => r.id === selectedRouteId) ?? null;
  const hasDetail = !!selectedCandidate?.segments && selectedCandidate.segments.length > 0;

  const isMobile = useIsMobile();

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
  // コードレビュー指摘の修正: 以前はこのファイル自身の凡例・絞り込みサマリ計算
  // （staticLegendHiddenKeysByAxis・staticFilterSummaries、下記）だけがビルド時静的
  // STATIC_FILTER_AXESのまま取り残されており、軸スタジオで新規公開したramp軸の凡例・
  // 絞り込み操作がこの画面のサマリ表示・MapLayersPanelへ一切反映されなかった
  // （MapView.tsx側は既にbuildStaticFilterAxes(rampAxes)へ移行済み）。mapLayers/
  // roadSurfaceSharedLayerIdsと同じくaxisCatalog.rampAxesから都度組み立てる。
  const staticFilterAxes = useMemo(() => buildStaticFilterAxes(axisCatalog.rampAxes), [axisCatalog.rampAxes]);
  // 改善計画T63: 道路情報以外の絞り込み可能レイヤー（車ストレス・自転車インフラ・指定路線・
  // 停止要因POI・事故の当事者/重大度）。roadHiddenKeysByModeと同じ理由でuseMemoにより
  // 参照を安定させる。
  const staticLegendHiddenKeysByAxis = useMemo(
    () =>
      Object.fromEntries(
        staticFilterAxes.map((axis) => [axis.axisId, hiddenLegendKeysByMode[axis.axisId] ?? NO_HIDDEN_LEGEND_KEYS]),
      ) as unknown as Record<StaticFilterAxisId, readonly string[]>,
    [staticFilterAxes, hiddenLegendKeysByMode],
  );
  const hiddenRouteLegendKeys = hiddenLegendKeysByMode[routeStyleModeId] ?? NO_HIDDEN_LEGEND_KEYS;
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
  // 道路情報の「すべて表示/すべて隠す」一括操作（1軸分の非表示キー全体の置き換え）。
  // 個別チェックはtoggleHiddenLegendKeyをそのまま使う（絞り込みは即時反映、T31。
  // レイヤーの自動ONはMapLayersPanel側が担う）。
  const handleRoadAxisSetHidden = useCallback(
    (axisId: RoadFilterAxisId, hiddenKeys: string[]) => {
      setHiddenLegendKeysByMode((prev) => ({ ...prev, [axisId]: hiddenKeys }));
    },
    [setHiddenLegendKeysByMode],
  );
  // 道路情報以外の絞り込み可能レイヤーの「すべて表示/すべて隠す」一括操作。
  // handleRoadAxisSetHiddenと同じ実装（軸idをキーに非表示配列を丸ごと差し替えるだけ）だが、
  // 呼び出し側の型（StaticFilterAxisId）を分けて誤った軸idの取り違えを防ぐ。
  const handleStaticFilterAxisSetHidden = useCallback(
    (axisId: StaticFilterAxisId, hiddenKeys: string[]) => {
      setHiddenLegendKeysByMode((prev) => ({ ...prev, [axisId]: hiddenKeys }));
    },
    [setHiddenLegendKeysByMode],
  );
  const handleRouteLegendToggle = useCallback(
    (key: string) => toggleHiddenLegendKey(routeStyleModeId, key),
    [routeStyleModeId, toggleHiddenLegendKey],
  );
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

  // 改善計画T167で導入した「推定指標をONにすると材料の観測データレイヤーも連動ON」する
  // カスケードは撤去した（改善計画T181フォローアップ、実機フィードバック「自由にメンバを
  // 表示非表示できることで、裏で表示状態で残るのは避けたい」）。T181で観測グループの
  // メンバーを個別に「表示項目の設定」で非表示にできるようになった結果、非表示にした
  // メンバーが推定指標側の操作で裏からONにされてしまうと、非表示設定でチップ自体が
  // 隠れているためユーザーがOFFに戻す手段を失う（T181で解消したはずの「チップからは
  // 消えたのに地図には出続ける」不整合が推定側の操作から再発する）。代わりに、推定軸の
  // 材料がどれか（どの観測データが計算に使われているか）は`renderMaterialsNote`
  // （MapOverlayControls.tsx、T167で導入済み）が▼展開時に「材料: ○○」として常に示すため、
  // 連動ONで自動的に地図へ出す必要性は薄いと判断した。
  const handleLayerToggle = useCallback(
    (id: MapLayerId, on: boolean) => {
      setLayerVisibility((prev) => ({ ...prev, [id]: on }));
    },
    [setLayerVisibility],
  );

  // 地図上（MapOverlayControls）のサマリ行に出す「適用中の条件」の1行要約。改善計画T165で
  // 「道路情報」が路面の種類（roadSurface）・道路の種類（roadType）の論理2レイヤーへ
  // 分割されたため、軸ごとに個別のサマリ・内訳を持つ（以前は1つのroadSummary/
  // roadLegendDetailsで2軸をまとめていた）。ズーム不足の案内は絞り込みより優先する
  // （ONにしたのに何も出ない状態の説明が先）。
  const roadSurfaceAxis = getRoadFilterAxis(ROAD_LINE_COLOR_AXIS_ID);
  const roadSurfaceFilterSummary = useMemo(
    () =>
      summarizeLegendFilters([
        {
          label: "",
          legend: roadSurfaceAxis.legend,
          hiddenKeys: roadHiddenKeysByMode[roadSurfaceAxis.id] ?? NO_HIDDEN_LEGEND_KEYS,
        },
      ]),
    [roadSurfaceAxis, roadHiddenKeysByMode],
  );
  const roadSurfaceSummary = regionZoomTooWide ? "ズームインすると表示されます" : roadSurfaceFilterSummary;
  const roadSurfaceLegendDetails = useMemo<LegendFilterSummaryAxis[]>(
    () =>
      regionZoomTooWide
        ? []
        : [
            {
              label: "",
              legend: roadSurfaceAxis.legend,
              hiddenKeys: roadHiddenKeysByMode[roadSurfaceAxis.id] ?? NO_HIDDEN_LEGEND_KEYS,
            },
          ],
    [regionZoomTooWide, roadSurfaceAxis, roadHiddenKeysByMode],
  );

  const roadTypeAxis = getRoadFilterAxis(ROAD_LINE_WIDTH_AXIS_ID);
  const roadTypeFilterSummary = useMemo(
    () =>
      summarizeLegendFilters([
        { label: "", legend: roadTypeAxis.legend, hiddenKeys: roadHiddenKeysByMode[roadTypeAxis.id] ?? NO_HIDDEN_LEGEND_KEYS },
      ]),
    [roadTypeAxis, roadHiddenKeysByMode],
  );
  const roadTypeSummary = regionZoomTooWide ? "ズームインすると表示されます" : roadTypeFilterSummary;
  const roadTypeLegendDetails = useMemo<LegendFilterSummaryAxis[]>(
    () =>
      regionZoomTooWide
        ? []
        : [
            { label: "", legend: roadTypeAxis.legend, hiddenKeys: roadHiddenKeysByMode[roadTypeAxis.id] ?? NO_HIDDEN_LEGEND_KEYS },
          ],
    [regionZoomTooWide, roadTypeAxis, roadHiddenKeysByMode],
  );
  // ルートは色分けモード自体が「何の条件で色分け中か」の情報なので常に出す
  const routeSummary = hasDetail
    ? `色分け: ${getRouteStyleMode(routeStyleModeId).label}${hiddenRouteLegendKeys.length > 0 ? "・一部非表示" : ""}`
    : null;
  const routeLegendDetails = useMemo<LegendFilterSummaryAxis[]>(
    () =>
      hasDetail
        ? [{ label: "", legend: getRouteStyleMode(routeStyleModeId).legend, hiddenKeys: hiddenRouteLegendKeys }]
        : [],
    [hasDetail, routeStyleModeId, hiddenRouteLegendKeys],
  );

  // 改善計画T63: 道路情報以外の絞り込み可能レイヤーも、道路情報と同じ要約関数
  // （summarizeLegendFilters）でチップ下に適用中の絞り込みを表示する。レイヤーごとに
  // 保有する軸ぶん（事故のみ2軸、他は1軸）をまとめて渡す。
  const staticFilterSummaries = useMemo(() => {
    const result: Partial<
      Record<
        MapLayerId,
        {
          summary: string | null;
          legendDetails: LegendFilterSummaryAxis[];
        }
      >
    > = {};
    const layerIds = new Set(staticFilterAxes.map((axis) => axis.layerId));
    for (const layerId of layerIds) {
      const axes = staticFilterAxes.filter((axis) => axis.layerId === layerId).map((axis) => ({
        label: axis.label ?? "",
        legend: axis.legend,
        hiddenKeys: staticLegendHiddenKeysByAxis[axis.axisId] ?? NO_HIDDEN_LEGEND_KEYS,
      }));
      result[layerId] = {
        summary: summarizeLegendFilters(axes),
        legendDetails: axes,
      };
    }
    return result;
  }, [staticFilterAxes, staticLegendHiddenKeysByAxis]);

  // 改善計画T308: MAP_LAYERS（静的フォールバック）ではなく、axisCatalog.rampAxes
  // （実行時フェッチ、軸スタジオの公開軸を含む）から組み立てたレイヤーカタログを使う。
  const mapLayers = useMemo(() => buildMapLayers(axisCatalog.rampAxes), [axisCatalog.rampAxes]);
  const roadSurfaceSharedLayerIds = useMemo(
    () => buildRoadSurfaceSharedLayerIds(axisCatalog.rampAxes),
    [axisCatalog.rampAxes]
  );

  // 地図上のチップ行はレイヤーカタログ（mapLayers）から組み立てる。レイヤーを追加したら
  // summaryの対応をここへ1行足すだけでよい（チップ・凡例パネルの描画は汎用）。
  const overlayLayers = useMemo<OverlayLayerChip[]>(
    () =>
      mapLayers.map((layer) => {
        const disabled = layer.id === "route" && !hasDetail;
        const summary =
          layer.id === "roadSurface"
            ? roadSurfaceSummary
            : layer.id === "roadType"
              ? roadTypeSummary
              : layer.id === "route"
                ? routeSummary
                : (staticFilterSummaries[layer.id]?.summary ?? null);
        const legendDetails =
          layer.id === "roadSurface"
            ? roadSurfaceLegendDetails
            : layer.id === "roadType"
              ? roadTypeLegendDetails
              : layer.id === "route"
                ? routeLegendDetails
                : layer.id === "precipitationNowcast"
                  ? PRECIPITATION_LEGEND_DETAILS
                  : layer.id === "windVector"
                    ? WIND_LEGEND_DETAILS
                    : layer.id === "thunderNowcast"
                      ? THUNDER_LEGEND_DETAILS
                      : layer.id === "tornadoNowcast"
                        ? TORNADO_LEGEND_DETAILS
                        : staticFilterSummaries[layer.id]?.legendDetails;
        // ユーザー判断（2026-08-25）: 動的グループ（降水ナウキャスト・風・雷・竜巻）は
        // 絞り込み機能を持たないため「地図の見え方」パネルの行自体を撤去した
        // （MapLayersPanel.tsx参照）。地図上チップの▶パネル本体へ説明文を常時表示する
        // 対応は「読みにくい」というフィードバックを受けて取りやめた（凡例のみを表示する）。
        // 改善計画T334: 上記とは別に、折りたたみ中の「表示する項目を選ぶ」設定パネル
        // （MapOverlayControls.tsx: renderVisibilitySettings）側は、各メンバー行に個別の
        // 情報アイコンを置き、押したメンバーだけ説明文を表示する形で復活させた
        // （panelHintは推定/観測/動的の全メンバーへ渡す。同時に常時表示にはしないため
        // 上記のT317同日追記の判断とは矛盾しない）。
        const isDynamicGroupLayer =
          layer.id === "precipitationNowcast" ||
          layer.id === "windVector" ||
          layer.id === "thunderNowcast" ||
          layer.id === "tornadoNowcast";
        return {
          id: layer.id,
          label: layer.label,
          chipLabel: layer.chipLabel ?? layer.label,
          on: layerVisibility[layer.id],
          disabled,
          // 動的グループはサイドバーに設定行が無くなったため「[設定はサイドバー]」を付けない。
          title: disabled
            ? "ルートを生成・選択すると使えます"
            : isDynamicGroupLayer
              ? layer.description
              : `${layer.description}[設定はサイドバー]`,
          summary,
          legendDetails,
          // 地図上チップのカテゴリ束ね（改善計画T128、MapOverlayControls.tsx）用。
          category: layer.category,
          dataNature: layer.dataNature,
          // 改善計画T334: 「表示する項目を選ぶ」設定パネルの個別情報アイコン用の説明文。
          panelHint: layer.panelHint,
        };
      }),
    [
      hasDetail,
      layerVisibility,
      roadSurfaceLegendDetails,
      roadSurfaceSummary,
      roadTypeLegendDetails,
      roadTypeSummary,
      routeLegendDetails,
      routeSummary,
      staticFilterSummaries,
      mapLayers,
    ],
  );

  // 全レイヤー一括OFF（ユーザー要望「一次・二次・動的まとめて1ボタンでクリアしたい」「ルート等も
  // 含めて全チップをOffにするのがシンプル」）。以前はMapOverlayControls.tsxが自前で
  // 持っていたが、地図下部中央の時刻スライダー隣へボタンを移設した（実機フィードバック
  // 「左上の全クリアアイコンをスライドバーの左側に移動して」）ため、layers/onToggleを
  // 既に持つこちらへ持ってきた。何もONでないときはno-opのため無効化する（誤操作の
  // 起点自体を減らす）。
  const hasAnyLayerOn = overlayLayers.some((layer) => layer.on);
  const handleClearAllLayers = useCallback(() => {
    for (const layer of overlayLayers) {
      if (layer.on) handleLayerToggle(layer.id, false);
    }
  }, [overlayLayers, handleLayerToggle]);

  // モバイルタブバーのボタン操作。同じタブを再タップしたら閉じる（トグル）。
  const handleMobileTabClick = useCallback((sheet: "routeSettings" | "routeOutcome" | "map") => {
    setMobileSheet((prev) => (prev === sheet ? null : sheet));
  }, []);

  // 下部シートの高さ変更。ドラッグ中/キー操作中は見た目の即時反映のみ（onHeightChange）、
  // 確定時のみ保存する（onHeightCommit。ドラッグ中の毎フレーム書き込みを避けるため、
  // useStoredStateのautoSave: falseとcommitMobileSheetHeightで分離している）。
  const handleMobileSheetHeightChange = useCallback(
    (vh: number) => {
      setMobileSheetHeightVh(vh);
    },
    [setMobileSheetHeightVh],
  );

  // MapViewからのビューポート通知（改善計画T180、MapView.tsx: onViewportChange参照）。
  const handleViewportChange = useCallback((viewport: MapViewport) => {
    setMapViewport(viewport);
  }, []);

  // 現在地が変わったらその地点の天候を取得(ルート生成時の風評価の起点にもなる)。
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

  // マウント直後はDEFAULT_LOCATION、その直後にGeolocationが成功すると実際の現在地で
  // locationが変わる。以前は固定時間（1.5秒）のデバウンスでこれを間引いていたが、
  // Geolocationの許可ダイアログへの応答等でその時間を超えることが多く、結局
  // DEFAULT_LOCATIONぶん＋実地点ぶんの2回Open-Meteoへ問い合わせてしまっていた
  // （実機フィードバック「天候がすぐ出てその後リフレッシュされる」＝時間ベースの間引きでは
  // 解決しない構造的な問題だったと判明）。マウント時の自動取得が確定するまで
  // （locationReady、useLocation.ts参照）待ってから1回だけfetchWeatherForする形にし、
  // 「いつ確定するか分からない」ものを固定時間の推測で間引くのをやめた。確定後
  // （handleLocateMeによる再取得等）はlocationReadyがtrueのまま変わらないため、
  // locationの変化に即座に反応する（従来どおり遅延なし）。
  // effect本体からの直接同期setState呼び出しを避け、マイクロタスク経由で実行する
  // （react-hooks/set-state-in-effect対策、SystemStatusPanel.tsxと同じ流儀）。
  useEffect(() => {
    if (!locationReady) return;
    Promise.resolve().then(() => fetchWeatherFor(location));
  }, [locationReady, location, fetchWeatherFor]);

  // 警報・注意報バッジ（改善計画T205）。天候と同じ「locationReadyになるまで待つ」方式
  // （上記参照）。通信エラー時は例外を投げるだけで、警報なし（空配列）として静かに扱う
  // （バックエンド自体が失敗時に空warningsを返す契約のため、これは主にネットワーク到達
  // 不能等の場合。T205完了条件「取得失敗時は警告なし」）。
  const latestWarningsRequestId = useRef(0);
  const fetchWarningsFor = useCallback((next: Coordinates) => {
    const requestId = ++latestWarningsRequestId.current;
    getWeatherWarnings(next)
      .then((result) => {
        if (requestId !== latestWarningsRequestId.current) return;
        setWeatherWarnings(result);
      })
      .catch(() => {
        if (requestId !== latestWarningsRequestId.current) return;
        setWeatherWarnings(null);
      });
  }, []);

  useEffect(() => {
    if (!locationReady) return;
    Promise.resolve().then(() => fetchWarningsFor(location));
  }, [locationReady, location, fetchWarningsFor]);

  // WBGT警告バッジ（改善計画T174）。警報・注意報バッジと同じ「locationReadyになるまで
  // 待つ」方式。提供期間外（11〜3月）・取得失敗・「ほぼ安全」のいずれもbackend契約どおり
  // level=nullとして静かに扱う。
  const latestWbgtRequestId = useRef(0);
  const fetchWbgtFor = useCallback((next: Coordinates) => {
    const requestId = ++latestWbgtRequestId.current;
    getWbgtStatus(next)
      .then((result) => {
        if (requestId !== latestWbgtRequestId.current) return;
        setWbgtStatus(result);
      })
      .catch(() => {
        if (requestId !== latestWbgtRequestId.current) return;
        setWbgtStatus(null);
      });
  }, []);

  useEffect(() => {
    if (!locationReady) return;
    Promise.resolve().then(() => fetchWbgtFor(location));
  }, [locationReady, location, fetchWbgtFor]);

  // 河川氾濫予報バッジ（改善計画T212）。他の警告バッジと同じ「locationReadyになるまで
  // 待つ」方式。取得失敗・対象河川なしのいずれもbackend契約どおりforecasts=[]として
  // 静かに扱う。
  const latestFloodRequestId = useRef(0);
  const fetchFloodForecastsFor = useCallback((next: Coordinates) => {
    const requestId = ++latestFloodRequestId.current;
    getFloodForecasts(next)
      .then((result) => {
        if (requestId !== latestFloodRequestId.current) return;
        setFloodForecasts(result);
      })
      .catch(() => {
        if (requestId !== latestFloodRequestId.current) return;
        setFloodForecasts(null);
      });
  }, []);

  useEffect(() => {
    if (!locationReady) return;
    Promise.resolve().then(() => fetchFloodForecastsFor(location));
  }, [locationReady, location, fetchFloodForecastsFor]);

  const warningBadgeItems = useMemo<WarningBadgeItem[]>(() => {
    const jmaItems: WarningBadgeItem[] = weatherWarnings
      ? weatherWarnings.warnings.map((warning) => ({
          id: warning.code,
          label: warning.name,
          level: warning.level as WarningBadgeItem["level"],
          source: "jma",
          title: [
            warning.additions.length > 0 ? `付随事項: ${warning.additions.join("・")}` : null,
            "取得できない場合は警報が出ていてもバッジが表示されないことがあります",
          ]
            .filter(Boolean)
            .join(" / "),
        }))
      : [];
    // WBGTはlevelがnull（提供期間外・取得失敗・「ほぼ安全」のいずれか）の間は表示しない
    // （T174完了条件、JMA警報が0件の場合と同じ「無ければ何も出ない」挙動）。
    const wbgtItem: WarningBadgeItem[] =
      wbgtStatus?.level && wbgtStatus.value != null
        ? [
            {
              id: "wbgt",
              label: `暑さ指数${wbgtStatus.label ?? ""}`,
              level: wbgtStatus.level as WarningBadgeItem["level"],
              source: "wbgt",
              title: `暑さ指数 ${wbgtStatus.value.toFixed(1)} / 取得できない場合は警戒レベルに関わらずバッジが表示されないことがあります`,
            },
          ]
        : [];
    // 河川氾濫予報（T212）。対象河川が無い/取得失敗の間はforecasts=[]のため何も出ない。
    const floodItems: WarningBadgeItem[] = (floodForecasts?.forecasts ?? []).map((forecast) => ({
      id: `flood-${forecast.river_code}`,
      label: forecast.label,
      level: forecast.badge_level as WarningBadgeItem["level"],
      source: "flood",
      title: `${forecast.condition} / 取得できない場合は氾濫予報が出ていてもバッジが表示されないことがあります`,
    }));
    return [...jmaItems, ...wbgtItem, ...floodItems];
  }, [weatherWarnings, wbgtStatus, floodForecasts]);

  // 降水ナウキャストの時刻一覧（改善計画T170/T171）。レイヤーがONの間だけ取得し、
  // 実況が5分毎に更新されるのに合わせて定期的に再取得する（OFFの間はfetch自体しない、
  // 他の外部APIと同じ「表示中のものだけ叩く」方針）。取得失敗時は例外を投げず
  // nowcastErrorへ記録する（precipitationNowcast.tsのfetchNowcastFramesは両方失敗時のみ
  // 例外、片方だけの失敗は部分的な結果を返すため、ここへ来るのは両方失敗した場合のみ）。
  const NOWCAST_REFRESH_INTERVAL_MS = 5 * 60 * 1000;
  const showPrecipitationNowcast = layerVisibility.precipitationNowcast;
  useEffect(() => {
    if (!showPrecipitationNowcast) return;
    let cancelled = false;
    const load = async (isFirstLoad: boolean) => {
      if (isFirstLoad) setNowcastLoading(true);
      try {
        // 実況（targetTimes_N1）は現在時刻より前ぶんを多く含む（実機確認: 2026-08-20時点で
        // 約3時間分）。過去の降水を振り返る用途はアプリの性質上無いため（実機フィードバック
        // 「過去の風、雨を気にすることはアプリの性質上ない、デフォルト位置を左端に」）、
        // trimToCurrentAndFutureで「現在」より前を切り捨て、スライダーの左端（index 0）が
        // 常に「現在」になるようにする。
        const frames = trimToCurrentAndFuture(await fetchNowcastFrames());
        if (cancelled) return;
        setNowcastFrames(frames);
        setNowcastError(null);
      } catch (error: unknown) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "降水ナウキャストの取得に失敗しました";
        // fetchNowcastFrames自体（jmaNowcastFrames.ts経由）はdebugLogへ記録済みだが、
        // ここ（catch側）でも失敗した事実自体をログする。取得失敗はUI（nowcastError→
        // dynamicLayerError）には出るがデバッグコンソールには出ていなかった
        // （2026-08-24実機調査で発覚した「異常があってもログに出ない」箇所の1つ）。
        debugLog("api:jma-nowcast-times", "降水ナウキャストの読み込みに失敗", { error: message }, "error");
        setNowcastError(message);
      } finally {
        if (!cancelled && isFirstLoad) setNowcastLoading(false);
      }
    };
    Promise.resolve().then(() => load(true));
    const intervalId = window.setInterval(() => load(false), NOWCAST_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showPrecipitationNowcast]);

  // 雷・竜巻の時刻一覧（改善計画T204）。雷ナウキャスト・竜巻発生確度ナウキャストは同じ
  // targetTimes_N3.json由来のため、どちらか一方でもONの間だけ1本のfetchで両方をカバーする
  // （nowcastFramesと同じ理由・同じ更新間隔。雷は10分毎更新のためnowcastの5分より長くても
  // 足りるが、揃えておく方が実装として単純なため同じ間隔にした）。
  const showThunderNowcast = layerVisibility.thunderNowcast;
  const showTornadoNowcast = layerVisibility.tornadoNowcast;
  useEffect(() => {
    if (!showThunderNowcast && !showTornadoNowcast) return;
    let cancelled = false;
    const load = async (isFirstLoad: boolean) => {
      if (isFirstLoad) setThunderNowcastLoading(true);
      try {
        const frames = trimToCurrentAndFuture(await fetchThunderNowcastFrames());
        if (cancelled) return;
        setThunderNowcastFrames(frames);
        setThunderNowcastError(null);
      } catch (error: unknown) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "雷ナウキャストの取得に失敗しました";
        // 降水ナウキャストのcatchと同じ理由でログする（2026-08-24実機調査）。
        debugLog("api:jma-nowcast-times", "雷・竜巻ナウキャストの読み込みに失敗", { error: message }, "error");
        setThunderNowcastError(message);
      } finally {
        if (!cancelled && isFirstLoad) setThunderNowcastLoading(false);
      }
    };
    Promise.resolve().then(() => load(true));
    const intervalId = window.setInterval(() => load(false), NOWCAST_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showThunderNowcast, showTornadoNowcast]);

  const showWindVector = layerVisibility.windVector;
  // 風・降水延長予報（T183、ユーザー要望「風と同じ考え方で、風と汎用化して実装してほしい」）
  // が共有する格子点マップのフェッチ（useWeatherGrid.ts参照）。バックエンドは1回のOpen-Meteo
  // 呼び出しで風向・風速・降水量をまとめて返すため、どちらか一方でもONならenabledにすることで
  // 両方ONのときも1本のフェッチで済む。gridは常に「現在」から始まる粗い格子（フレーム時刻軸が
  // 使う）、effectiveGridは詳細格子があればそちらを優先した表示用の格子（gridMark/gridFillの
  // ジオメトリ計算に使う）。effectiveGridSpacingDegはeffectiveGridの実際の格子間隔（T185で
  // ズーム依存になったため、gridFillのセルサイズはここから得た値をそのまま使う）。
  const {
    grid: windGrid,
    effectiveGrid: effectiveWindGrid,
    effectiveGridSpacingDeg,
    loading: windLoading,
    error: windError,
  } = useWeatherGrid(showWindVector || showPrecipitationNowcast, mapViewport);

  // 各要素のフレーム列（データ層、dynamicWeather.ts: DynamicWeatherFrame[]）。表示層は
  // ここから先、どの要素がどのデータソースから来ているかを一切意識しない
  // （T183再設計「データ取得の差異はデータ層で吸収」）。
  const windFramesList = useMemo(() => windFrames(windGrid), [windGrid]);
  const precipFramesList = useMemo(() => precipitationFrames(nowcastFrames, windGrid), [nowcastFrames, windGrid]);
  // 雷・竜巻は同じthunderNowcastFrames（targetTimes_N3.json由来）を共有する1本のフレーム列
  // （改善計画T204）。雷ナウキャストと違い延長予報を持たないため、precipFramesListのような
  // 複数ソース統合は不要（thunderFramesがそのままdynamicWeather.tsの共通フレーム列を返す）。
  const thunderFramesList = useMemo(() => thunderFrames(thunderNowcastFrames), [thunderNowcastFrames]);

  // ONの全レイヤーのフレーム時刻を統合した共有タイムライン（T183再設計、実機フィードバック
  // 「時間経過はスライドバー1本で表現する」）。降水ナウキャスト（5分刻み）と風・延長予報
  // （1時間刻み）が混ざると、目盛りが「近い将来は細かく、遠い将来は粗い」を自然に実現する
  // （個別のUIロジックは不要）。
  const activeFrameLists = useMemo(() => {
    const lists: { time: Date }[][] = [];
    if (showWindVector) lists.push(windFramesList);
    if (showPrecipitationNowcast) lists.push(precipFramesList);
    if (showThunderNowcast || showTornadoNowcast) lists.push(thunderFramesList);
    return lists;
  }, [
    showWindVector,
    windFramesList,
    showPrecipitationNowcast,
    precipFramesList,
    showThunderNowcast,
    showTornadoNowcast,
    thunderFramesList,
  ]);
  const timeline = useMemo(() => mergeFrameTimes(activeFrameLists), [activeFrameLists]);

  // スライダーのつまみ位置（共有のdynamicLayerTargetTimeに最も近いタイムライン上のindex）と、
  // 表示用ラベル列。
  const sliderIndex = useMemo(() => nearestTimeIndex(timeline, dynamicLayerTargetTime), [timeline, dynamicLayerTargetTime]);
  // hourMark/tickLabelは実機フィードバック「メモリを簡潔に出して」「横スクロールでメモリの
  // 方が移動するように」「ルーラーにもう少し目盛りを細かく表示して。日付部分は不要、時刻
  // のみ。時刻も細いところは分だけにする等」への対応（DynamicLayerTimeSlider.tsx冒頭コメント
  // 参照）。正時判定はgetUTCMinutes()で行う（JSTはUTC+9:00ちょうどで分のずれが無いため、
  // 実行環境のローカルタイムゾーンに左右されずJSTの正時と一致する）。延長予報（60分以降）は
  // 全フレームが正時のため、hourMark（目盛りの線を太くするだけ）は毎コマ付けても密度の問題は
  // 無いが、tickLabel（目盛りの下に出す文字）を毎時間ぶん全部「HH:mm」で出すと目盛り間隔
  // （TICK_SPACING_PX）に対して文字が重なってしまう（実機Playwright確認で発覚）。2時間おきに
  // 間引くことで文字同士の重なりを避けつつ、以前（3時間おき）より密度を上げた。正時でない
  // 密なコマ（降水ナウキャストの5分刻み等）は文字自体を短い分のみ表記にできるため、間引かず
  // 毎コマぶん出す。
  const sliderFrames = useMemo<DynamicLayerTimeSliderFrame[]>(
    () =>
      timeline.map((time) => {
        const isHour = time.getUTCMinutes() === 0;
        return {
          label: formatDynamicFrameTime(time),
          hourMark: isHour,
          tickLabel: isHour
            ? time.getUTCHours() % 2 === 0
              ? formatDynamicFrameHourMinute(time)
              : undefined
            : formatDynamicFrameMinuteOnly(time),
        };
      }),
    [timeline]
  );
  // 「現在」に戻るボタン（改善計画、実機フィードバック「現況に戻すボタンも横に追加して」）の
  // ジャンプ先index。ボタンはフェッチのたびではなく毎回押された時点の「現在」に戻したいため、
  // timeline自体から都度計算する。
  const sliderCurrentIndex = useMemo(() => nearestTimeIndex(timeline, new Date()), [timeline]);

  // スライダー操作（改善計画、実機フィードバック「同じ日時を示した状態で連動させ、変えるのは
  // 感度（スライド時の差）だけ」→T183で1本のスライダーへ統合）。DynamicLayerTimeSlider自体の
  // onIndexChangeはタイムライン上のindexしか知らないため、ここで実時刻へ変換してから共有の
  // dynamicLayerTargetTimeへ書き込む（「現在」ボタン＝onIndexChange(sliderCurrentIndex)の
  // 呼び出しも同じ経路を通るため、別扱い不要）。
  const handleSliderIndexChange = useCallback(
    (index: number) => {
      const time = timeline[index];
      if (time) setDynamicLayerTargetTime(time);
    },
    [timeline]
  );
  const handleDynamicLayerNow = useCallback(() => setDynamicLayerTargetTime(new Date()), []);

  // 選択中の共有時刻（dynamicLayerTargetTime）に対応する各要素のペイロード。該当時刻がその
  // 要素のデータ範囲外なら描画しない（frameIndexForTimeがnullを返す、要件「該当時間データが
  // ない場合、地図には描画しない」。従来の「端のフレームへクランプして古いデータを見せ続ける」
  // 挙動は廃止）。表示層（MapView.tsx）はkindしか見ないため、降水がナウキャスト由来
  // （rasterTile）か延長予報由来（gridFill）かはここで既に吸収済み。
  const windPayload = useMemo(() => {
    const index = frameIndexForTime(windFramesList, dynamicLayerTargetTime);
    if (index == null || effectiveWindGrid.length === 0) return undefined;
    return windRenderPayload(effectiveWindGrid, windFramesList[index].ref);
  }, [windFramesList, dynamicLayerTargetTime, effectiveWindGrid]);
  const precipitationPayload = useMemo(() => {
    const index = frameIndexForTime(precipFramesList, dynamicLayerTargetTime);
    if (index == null) return undefined;
    return precipitationRenderPayload(nowcastFrames, effectiveWindGrid, effectiveGridSpacingDeg, precipFramesList[index].ref);
  }, [precipFramesList, dynamicLayerTargetTime, nowcastFrames, effectiveWindGrid, effectiveGridSpacingDeg]);
  // 雷・竜巻は同じフレーム列・同じrefを共有し、プロダクトコードだけが異なる
  // （thunderRenderPayload/tornadoRenderPayloadの違い、thunderNowcast.ts参照）。
  const thunderPayload = useMemo(() => {
    const index = frameIndexForTime(thunderFramesList, dynamicLayerTargetTime);
    if (index == null) return undefined;
    return thunderRenderPayload(thunderNowcastFrames, thunderFramesList[index].ref);
  }, [thunderFramesList, dynamicLayerTargetTime, thunderNowcastFrames]);
  const tornadoPayload = useMemo(() => {
    const index = frameIndexForTime(thunderFramesList, dynamicLayerTargetTime);
    if (index == null) return undefined;
    return tornadoRenderPayload(thunderNowcastFrames, thunderFramesList[index].ref);
  }, [thunderFramesList, dynamicLayerTargetTime, thunderNowcastFrames]);

  // MapViewへ渡す単一プロパティ（T183再設計、旧5個のprecipitation/wind個別propsを統合）。
  // 新しい動的気象要素を追加してもMapViewProps自体は変わらず、ここへ1エントリ足すだけでよい。
  const dynamicWeather = useMemo(
    () => ({
      windVector: { visible: showWindVector, payload: windPayload },
      precipitationNowcast: { visible: showPrecipitationNowcast, payload: precipitationPayload },
      thunderNowcast: { visible: showThunderNowcast, payload: thunderPayload },
      tornadoNowcast: { visible: showTornadoNowcast, payload: tornadoPayload },
    }),
    [
      showWindVector,
      windPayload,
      showPrecipitationNowcast,
      precipitationPayload,
      showThunderNowcast,
      thunderPayload,
      showTornadoNowcast,
      tornadoPayload,
    ]
  );

  // 共有スライダーのloading/error表示。windLoading/windErrorは両要素が使う格子点フェッチ
  // （useWeatherGrid、ONのどちらか一方でも走る）、nowcastLoading/nowcastErrorは降水ナウキャスト
  // 固有のフェッチ、thunderNowcastLoading/thunderNowcastErrorは雷・竜巻共有のフェッチ。
  // 風のみONならnowcast/thunderの状態は無関係（フェッチ自体走らない）。
  const dynamicLayerLoading =
    windLoading || (showPrecipitationNowcast && nowcastLoading) || ((showThunderNowcast || showTornadoNowcast) && thunderNowcastLoading);
  const dynamicLayerError =
    windError ??
    (showPrecipitationNowcast ? nowcastError : null) ??
    (showThunderNowcast || showTornadoNowcast ? thunderNowcastError : null);

  // 生成条件のうち重み設定の比較キー（上書き無効時はnull＝バックエンド既定値を表す）。
  // 改善計画T292: 車ストレス専用レシピ（旧car_stress_recipe等）は専用Pythonレシピの
  // 廃止に伴い比較対象から削除した。
  const currentWeightsKey = JSON.stringify({
    weights: weightOverrideEnabled ? { scoringWeights, routePreference } : null,
    // 改善計画T267: hard_filtersは常時送信するため、上書き系のようなnull分岐を持たず
    // 常に比較対象へ含める。
    hardFilters,
  });

  // 表示中の候補の生成条件と現在のフォーム値がずれているか（生成条件系は「生成ボタンで
  // 反映」のため、編集しただけでは何も起きない。それをヒントとして可視化する、T31）
  const conditionsDirty =
    generatedConditions != null &&
    routes.length > 0 &&
    (location.latitude !== generatedConditions.latitude ||
      location.longitude !== generatedConditions.longitude ||
      routeMode !== generatedConditions.routeMode ||
      (generatedConditions.routeMode === "loop" && Number(distanceInput) !== generatedConditions.distanceKm) ||
      currentWeightsKey !== generatedConditions.weightsKey);

  async function handleGenerate(distanceKm: number) {
    setLoading(true);
    setErrorMessage(null);
    try {
      // 改善計画T303: 送信直前にキー整合を補正する（上のコメント参照）。RouteSettingsPanel
      // がマウント済みならこの時点で既にキーは一致しており synced は null になる。
      // 改善計画T320: axisCatalog.defaultWeights自体がまだ軸スタジオの現在状態を反映して
      // いない（axisCatalog.loaded===false、未取得・取得失敗）場合、この同期は静的フォール
      // バック（既存7軸）に合わせてroutePreferenceを書き換えてしまい、実際の公開軸集合とは
      // 無関係な値になる。この場合はroute_preference自体を省略し、backend側の既定値
      // （load_route_preference、常に最新のAXIS_DEFINITIONS由来）に委ねる方が安全
      // （scoring_weightsは軸レジストリと無関係なため引き続き送る）。
      const syncedRoutePreference = axisCatalog.loaded
        ? (syncRoutePreferenceKeys(routePreference, axisCatalog.defaultWeights) ?? routePreference)
        : null;
      // 改善計画T365-2: 周回モードでは経由地・目的地の値が残っていても送らない
      // （モード切り替え自体は値を消さないため、地図上にピンが残っていても周回モード中は
      // 無視する。地図表示もrouteMode==="destination"のときだけ、page.tsx→MapView.tsx参照）。
      // 目的地モードでは距離をRouteForm（distanceKm=0固定）から受け取らず、地図上の
      // 経由地・目的地から自動算出する。distance_kmはbackendのbbox見積り半径のほか、
      // 「起点から近すぎる=distance_km未満」バリデーション（routes.py:
      // _check_waypoints_within_range）の基準にもなるため、実際に指定した点の最遠距離を
      // 必ず上回る値にする（+1kmの余裕、MAX_DISTANCE_KMで頭打ち）。
      const destinationModePoints = routeMode === "destination" ? [...waypoints, ...(destination ? [destination] : [])] : [];
      const effectiveDistanceKm =
        routeMode === "destination"
          ? Math.min(MAX_DISTANCE_KM, Math.ceil(Math.max(...destinationModePoints.map((p) => haversineKm(location, p)))) + 1)
          : distanceKm;
      const { routes: candidates, conditions, engine } = await generateRoutes({
        latitude: location.latitude,
        longitude: location.longitude,
        distance_km: effectiveDistanceKm,
        distance_tolerance_km: DISTANCE_TOLERANCE_KM,
        route_type: "loop",
        penalty_strength: 1.0,
        // 改善計画T267: hard_filtersは一般向けルート設定画面（RouteSettingsPanel）が
        // 常時操作する対象のため、weightOverrideEnabledのような上書き専用トグルを介さず
        // 常に送る（既定値はbackendのDEFAULT_HARD_FILTERSと一致するため挙動は変わらない）。
        hard_filters: hardFilters,
        ...(weightOverrideEnabled ? { scoring_weights: scoringWeights } : {}),
        ...(weightOverrideEnabled && syncedRoutePreference ? { route_preference: syncedRoutePreference } : {}),
        // 改善計画T364/T365-2: 目的地モードのときだけ経由地・目的地を送る
        // （backend側の分岐はapi/routers/routes.py参照）。
        ...(routeMode === "destination" && waypoints.length > 0 ? { waypoints } : {}),
        ...(routeMode === "destination" && destination ? { destination } : {}),
      });
      setRoutes(candidates);
      setSelectedRouteId(candidates[0]?.id ?? null);
      // dirty判定の基準は「いま表示している候補を作った条件」。エラー時は既存候補が
      // 残るため更新しない（tryの成功パスでのみ更新する）
      setGeneratedConditions({
        latitude: location.latitude,
        longitude: location.longitude,
        distanceKm: effectiveDistanceKm,
        weightsKey: currentWeightsKey,
        routeMode,
      });
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
      const message = error instanceof Error ? error.message : "不明なエラーが発生しました";
      // generateRoutes（routeApi.ts: postJson）自体の失敗は既にそちらでdebugLog記録済みだが、
      // ここに来る他の例外（候補構築中の想定外エラー等）も含め、ルート生成ハンドラの失敗として
      // ここでも記録する（2026-08-24実機調査「fail to fetchがどこにもログされない」を受けて
      // 監査、多層防御として残す）。
      debugLog("api:route", "ルート生成ハンドラで例外", { error: message }, "error");
      setErrorMessage(message);
    } finally {
      setLoading(false);
    }
  }

  // 「ルートを作る」ブロックの中身（天候・アプリ名は常設ヘッダへ移動済み、T36/T37）。
  // デスクトップの<details>専用（改善計画T250でモバイルはヘッダーの操作バーへ出発地点・
  // 距離・生成ボタンを分離済み。改善計画T300でモバイルの結果表示自体も「ルート設定」
  // 「ルート結果」の2タブへ分割したため、デスクトップはその両方を続けて呼ぶことで
  // 従来どおり1つの折りたたみ内に収める）。
  function renderRouteSectionBody() {
    return (
      <>
        <LocationControl location={location} source={locationSource} />

        <RouteForm
          distance={distanceInput}
          onDistanceChange={setDistanceInput}
          onGenerate={handleGenerate}
          loading={loading}
          routeMode={routeMode}
          onRouteModeChange={handleRouteModeChange}
          waypointCount={waypoints.length}
          onWaypointsClear={handleWaypointsClear}
          destinationState={destinationState}
          onDestinationButtonClick={handleDestinationButtonClick}
        />
        {errorMessage && <ErrorText>{errorMessage}</ErrorText>}
        {renderRouteSettingsSectionBody()}
        {renderRouteOutcomeSectionBody()}
      </>
    );
  }

  // 一般ユーザー向けルート設定（改善計画T267、目論見書4章）。0次(除外)・軸選択・重みを
  // 生成前に調整できる、常時表示のメイン導線。研究モードのWeightPanelとはroute_preference
  // （weightOverrideEnabled）の状態を共有する（page.tsx冒頭のstate宣言・handleGenerateの
  // コメント参照）。モバイルの「ルート設定」タブ、デスクトップの「ルートを作る」ブロック
  // 前半から呼ぶ（改善計画T300、旧renderRouteResultsBodyの前半を分離）。
  function renderRouteSettingsSectionBody() {
    return (
      <div className={layerPanelStyles.group}>
        <h2 className={layerPanelStyles.groupTitle}>ルート設定</h2>
        <RouteSettingsPanel
          hardFilters={hardFilters}
          onHardFiltersChange={setHardFilters}
          routePreference={routePreference}
          onRoutePreferenceChange={setRoutePreference}
          overrideEnabled={weightOverrideEnabled}
          onOverrideEnabledChange={setWeightOverrideEnabled}
        />
      </div>
    );
  }

  // 生成結果に関する表示（設定変更の警告・空状態ガイド・候補一覧・比較表・色分け設定、
  // ルート設定は含まない）。モバイルの「ルート結果」タブ、デスクトップの「ルートを作る」
  // ブロック後半から呼ぶ（改善計画T300、旧renderRouteResultsBodyの後半を分離）。
  function renderRouteOutcomeSectionBody() {
    return (
      <>
        {conditionsDirty && (
          <p className={styles.dirtyHint}>条件が変更されています。「ルート生成」を押すと反映されます</p>
        )}
        {/* 生成前の空状態には「まず何をするか」のガイドを出す（初見ユーザー向け、T30） */}
        {routes.length === 0 && !loading && !errorMessage && (
          <p className={styles.emptyHint}>
            距離を入れて「ルート生成」を押すと、周回ルートの候補が地図に表示されます
          </p>
        )}
        {/* 改善計画T365: 生成済みの候補一覧・地図描画・選択状態だけをリセットする
            （経由地・目的地のピンは対象外、別々のクリア操作として使い分ける）。 */}
        {routes.length > 0 && (
          <button type="button" className={styles.clearRoutesButton} onClick={handleRoutesClear}>
            ルートをクリア
          </button>
        )}
        <RouteList routes={routes} selectedRouteId={selectedRouteId} onSelect={setSelectedRouteId} />
        {/* 実験スロット比較表（研究インターフェース改善 §10-3）。研究モード中の生成が
            2件以上たまったときだけ表示する。生成結果の一覧という性質上、入力パラメータ
            （評価重み・車ストレスレシピ、renderResearchSectionBody参照）とは分け、
            RouteListの並びであるこのブロックに残す。 */}
        {researchEnabled && <ComparisonPanel slots={experimentSlots} axisLabels={axisCatalog.axisLabels} />}
        {renderRouteColorSectionBody()}
      </>
    );
  }

  // 「生成したルートの色分け」セクション（改善計画: 地図の見え方パネルのグルーピングを
  // 地図上チップと統一）。以前はMapLayersPanel（地図の見え方）内の独立見出しだったが、
  // 「ルートを作る＝ルートに関する制御、地図の見え方＝地図自体の制御」という役割分担
  // （実機フィードバック）に沿って、選択中ルート自体の色分け設定はこちらへ移設した。
  // 見た目はMapLayersPanel.module.cssのクラスをそのまま再利用する（上記import参照）。
  // ルート未生成時の案内は、以前は「地図の見え方」から「ルートを作る」への誘導リンクを
  // 持っていたが、この移設によりリンク自体が不要になった（既にこのパネルの中にいるため）。
  function renderRouteColorSectionBody() {
    const routeStyleMode = getRouteStyleMode(routeStyleModeId);
    function handleRouteModeSelect(id: RouteStyleModeId) {
      setRouteStyleModeId(id);
      if (!layerVisibility.route) handleLayerToggle("route", true);
    }
    return (
      <div className={layerPanelStyles.group}>
        <h2 className={layerPanelStyles.groupTitle}>生成したルートの色分け</h2>
        {!hasDetail ? (
          <p className={layerPanelStyles.mutedHint}>ルートを生成・選択すると使えます。</p>
        ) : (
          <>
            <LayerChip
              label="表示"
              ariaLabel="ルートレイヤーを表示"
              on={layerVisibility.route}
              onClick={() => handleLayerToggle("route", !layerVisibility.route)}
            />
            {/* 単一選択のため矢印キーでの移動が期待される構成。以前は
                role="radiogroup"/role="radio"を手書きしていたが、roving tabindex（矢印キー
                移動）までは自前実装していなかったため、Radix RadioGroupへ置き換えて標準で
                備わるようにした（T253併用導入）。 */}
            <RadioGroup.Root
              aria-label="ルートの色分け"
              className={layerPanelStyles.modeGroup}
              value={routeStyleModeId}
              onValueChange={(id) => handleRouteModeSelect(id as RouteStyleModeId)}
            >
              {ROUTE_STYLE_MODES.map((mode) => (
                <RadioGroup.Item
                  key={mode.id}
                  value={mode.id}
                  className={
                    mode.id === routeStyleModeId
                      ? `${layerPanelStyles.modeItem} ${layerPanelStyles.modeItemActive}`
                      : layerPanelStyles.modeItem
                  }
                >
                  {mode.label}
                </RadioGroup.Item>
              ))}
            </RadioGroup.Root>
            <div className={layerPanelStyles.legendCheckboxList}>
              {routeStyleMode.legend.map((entry) => {
                const visible = !hiddenRouteLegendKeys.includes(entry.key);
                const rowClassName = entry.isFallback
                  ? `${layerPanelStyles.legendCheckboxRow} ${layerPanelStyles.legendCheckboxRowFallback}`
                  : layerPanelStyles.legendCheckboxRow;
                return (
                  <label key={entry.key} className={rowClassName}>
                    <Checkbox checked={visible} onCheckedChange={() => handleRouteLegendToggle(entry.key)} aria-label={entry.label} />
                    <span className={layerPanelStyles.swatch} style={{ background: entry.color }} />
                    {entry.label}
                  </label>
                );
              })}
            </div>
          </>
        )}
      </div>
    );
  }

  // 「地図の見え方」の中身。改善計画T300: 「開発者」ブロック（旧称「設定」）廃止に伴い、
  // 地図インスタンス（refreshToken）に紐づく「地図データを再読み込み」ボタンをここへ
  // 移設した（デバッグログ切替はヘッダーのアイコンボタンへ移設、下記header参照。
  // 情報量が薄い独立ブロックとして維持する理由が無くなったため、両方とも他の場所へ
  // 移すだけで「開発者」ブロック自体は廃止した）。
  function renderMapSettingsSectionBody() {
    return (
      <Card>
        {/* 基礎地図・道路情報タイルのキャッシュ更新は日常操作ではない運用ボタン。
            このページが持つ地図インスタンス（refreshToken）に紐づくため、/adminへは
            移設せずここに残す。 */}
        <button type="button" onClick={() => setRefreshToken((v) => v + 1)} className={styles.refreshButton}>
          地図データを再読み込み
        </button>
        <MapLayersPanel
          layerVisibility={layerVisibility}
          onLayerToggle={handleLayerToggle}
          roadHiddenKeysByMode={roadHiddenKeysByMode}
          onRoadLegendToggle={toggleHiddenLegendKey}
          onRoadAxisSetHidden={handleRoadAxisSetHidden}
          staticFilterHiddenKeysByAxis={staticLegendHiddenKeysByAxis}
          onStaticFilterLegendToggle={toggleHiddenLegendKey}
          onStaticFilterAxisSetHidden={handleStaticFilterAxisSetHidden}
          regionZoomTooWide={regionZoomTooWide}
          layerDataStatus={layerDataStatus}
          hasHiddenFilters={hasHiddenFilters}
          onClearAllFilters={handleClearAllFilters}
          mapLayers={mapLayers}
          roadSurfaceSharedLayerIds={roadSurfaceSharedLayerIds}
          secondaryAxes={axisCatalog.secondaryAxes}
          staticFilterAxes={staticFilterAxes}
        />
      </Card>
    );
  }

  return (
    <div className={styles.viewport}>
      {/* 天候は生成条件（風評価の起点）だが、以前はサイドバー内の「ルートを作る」ブロックに
          埋もれてスマホで見づらいという実機フィードバックを受け、常設ヘッダへ移した
          （モバイル実機フィードバック対応T36）。デスクトップ・モバイル共通の1箇所。 */}
      <header
        className={styles.weatherHeader}
        title="風向・風速はルート候補の評価に使われます"
      >
        <WeatherPanel weather={weather} loading={weatherLoading} error={weatherError} />
        {/* 警報バッジ＋デバッグアイコンのグループ（UI改善: 上部バーの見切れ対応）。
            端末幅が狭い・警報の文言が長い等で.weatherHeader全体が入り切らない場合、
            以前はhtml,body{overflow-x:hidden}（globals.css）によってこのグループが
            画面外へサイレントに切れて完全に見えなくなっていた。.weatherHeaderを
            横スクロール可能にした上で、このグループをposition:stickyで右端に固定し、
            スクロールしても警報バッジが常に見える状態を保つ（「警報の存在に気づけない
            ことを避ける」という既存の安全側方針、WarningBadge.tsx冒頭コメント参照）。 */}
        <div className={styles.headerActions}>
          <WarningBadgeList items={warningBadgeItems} />
          {/* デバッグログの起動アイコン（改善計画T300）。以前は「開発者」タブ内のボタン
              だったが、そのタブ自体を廃止したためヘッダーへ移設した。debugEnabled時のみ
              表示（デバッグモードのON/OFF自体は/adminで切り替える、DebugConsole.tsx参照）。
              DebugConsole自体はposition:fixedのFloatingPanelベースで自己完結しており、
              JSXツリー上のどこに置いても見た目は変わらない。 */}
          {debugEnabled && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setDebugConsoleOpen((v) => !v)}
              aria-pressed={debugConsoleOpen}
              aria-label={debugConsoleOpen ? "デバッグログを隠す" : "デバッグログを表示"}
              title={debugConsoleOpen ? "デバッグログを隠す" : "デバッグログを表示"}
              className="shrink-0"
            >
              <LogIcon size={15} />
            </Button>
          )}
        </div>
      </header>
      <DebugConsole open={debugConsoleOpen} onClose={() => setDebugConsoleOpen(false)} />

      {/* モバイル専用の操作バー（改善計画T250）。「ルートを作る」タブを開かないと出発地点の
          確認も生成もできない、という導線の長さが実機フィードバックだったため、天候ヘッダー
          直下に常設し、地図を見ながらでも操作できるようにした。生成ボタンがタブの外に出た
          ことで、失敗時のエラーメッセージが見えなくなる回帰を避けるためここにも表示する
          （生成結果自体は下部「ルート結果」タブ、renderRouteOutcomeSectionBody参照）。 */}
      {isMobile && (
        <div className={styles.mobileActionBar}>
          <LocationControl location={location} source={locationSource} compact />
          <RouteForm
            distance={distanceInput}
            onDistanceChange={setDistanceInput}
            onGenerate={handleGenerate}
            loading={loading}
            compact
            routeMode={routeMode}
            onRouteModeChange={handleRouteModeChange}
            waypointCount={waypoints.length}
            onWaypointsClear={handleWaypointsClear}
            destinationState={destinationState}
            onDestinationButtonClick={handleDestinationButtonClick}
          />
          {errorMessage && <ErrorText>{errorMessage}</ErrorText>}
        </div>
      )}

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
                {/* サイドバーは「A. ルートを作る（生成条件系・生成ボタンで反映）」
                    「B. 地図の見え方（表示系・即時反映）」の2ブロック構成
                    （UI一貫性再編T30）。生成に効く条件（出発地点・距離・重み）が
                    画面のあちこちに分散していた状態を解消し、系統ごとに反映タイミングを揃える。
                    評価重み・車ストレスレシピの調整UI（旧「研究」ブロック）はT270で/adminへ
                    移設済み。運用/デバッグツール（旧「C. 開発者」ブロック、旧称「設定」）は
                    改善計画T300で廃止し、地図データ再読み込みボタンはB（地図の見え方）へ、
                    デバッグログ切替は常設ヘッダーのアイコンへそれぞれ移設した
                    （renderMapSettingsSectionBody・header部分参照）。 */}

                {/* A. ルートを作る: アプリの主機能のため最上部・デフォルト開。 */}
                <Disclosure
                  className={styles.blockSection}
                  triggerClassName={styles.blockSummary}
                  bodyClassName={styles.blockBody}
                  id={GENERATE_SECTION_TITLE_ID}
                  summary={
                    <>
                      <span aria-hidden="true" className={styles.blockChevron} />
                      ルートを作る
                    </>
                  }
                  open={generateOpen}
                  onOpenChange={setGenerateOpen}
                >
                  {renderRouteSectionBody()}
                </Disclosure>

                {/* B. 地図の見え方: レイヤーのON/OFF・凡例・絞り込み・色分けの設定はすべてここ。
                    地図の上（MapOverlayControls）にはON/OFFチップと適用中の条件の1行サマリだけを
                    残し、詳細は地図に重ねない（地図の視界を優先）。サマリのタップでこのパネルの
                    該当セクションへスクロールしてくる。 */}
                <section className={styles.blockSection}>
                  <h2 className={styles.blockHeading}>地図の見え方</h2>
                  {renderMapSettingsSectionBody()}
                </section>
              </>
            )}
          </aside>
        )}

        {/* app-map-paneはpage.module.css側のモバイル向けMapLibre帰属表示オフセット規則
            （.maplibregl-ctrl-bottom-*、globals.cssのapp-debug-console等と同じマーカークラスの
            手法）が参照するグローバルなマーカークラス。 */}
        <div className={`${styles.mapPane} app-map-pane`}>
          <MapView
            routes={routes}
            selectedRouteId={selectedRouteId}
            location={location}
            showElevation={layerVisibility.elevation}
            dynamicWeather={dynamicWeather}
            showRoadType={layerVisibility.roadType}
            showRoadSurface={layerVisibility.roadSurface}
            showDesignation={layerVisibility.designation}
            showTunnel={layerVisibility.tunnel}
            showOneway={layerVisibility.oneway}
            showStopPoi={layerVisibility.stopPoi}
            showSupplyPoi={layerVisibility.supplyPoi}
            showAccidents={layerVisibility.accidents}
            axisVisibility={axisVisibility}
            secondaryAxisCasingLayerIds={secondaryAxisCasingLayerIds}
            roadHiddenKeysByMode={debouncedRoadHiddenKeysByMode}
            staticLegendHiddenKeysByAxis={debouncedStaticLegendHiddenKeysByAxis}
            routeLayerOn={layerVisibility.route}
            routeStyleModeId={routeStyleModeId}
            hiddenRouteLegendKeys={hiddenRouteLegendKeys}
            onRegionZoomHintChange={setRegionZoomTooWide}
            onViewportChange={handleViewportChange}
            onLayerDataStatusChange={setLayerDataStatus}
            refreshToken={refreshToken}
            experimentSlots={researchEnabled ? experimentSlots : []}
            rampAxes={axisCatalog.rampAxes}
            axisLabels={axisCatalog.axisLabels}
            // 改善計画T365-2: 周回モード中は地図上のピンを表示・追加受付しない
            // （モード切り替え自体はwaypoints/destination state自体を消さないため、
            // 目的地モードへ戻れば復元される）。
            waypoints={routeMode === "destination" ? waypoints : []}
            onWaypointAdd={handleWaypointAdd}
            onWaypointRemove={handleWaypointRemove}
            destination={routeMode === "destination" ? destination : null}
            destinationArmed={routeMode === "destination" && destinationArmed}
            onDestinationSet={handleDestinationSet}
            onDestinationClear={handleDestinationClear}
            pinPlacementEnabled={routeMode === "destination"}
          />

          <MapOverlayControls layers={overlayLayers} onToggle={handleLayerToggle} secondaryAxes={axisCatalog.secondaryAxes} />

          {/* 地図下部中央の行。全レイヤー一括OFFボタン（実機フィードバック「左上の全クリア
              アイコンをスライドバーの左側に移動して」で旧MapOverlayControls左上から移設）+
              時刻依存レイヤーの時刻スライダーを横並びで置く。ボタンはレイヤーの種類を問わず
              常時押せる必要があるため無条件で出し、スライダーは時刻依存レイヤーが1つ以上ON
              のときだけ隣に出す（改善計画T170、設計原則12: 地図の視界を圧迫しない）。 */}
          <div className={styles.bottomControlRow}>
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
            {(showPrecipitationNowcast || showWindVector || showThunderNowcast || showTornadoNowcast) && (
              <div className={styles.dynamicLayerSliders}>
                <DynamicLayerTimeSlider
                  frames={sliderFrames}
                  index={sliderIndex}
                  onIndexChange={handleSliderIndexChange}
                  currentIndex={sliderCurrentIndex}
                  onNow={handleDynamicLayerNow}
                  loading={dynamicLayerLoading}
                  loadingLabel="気象データの時刻を取得中..."
                  error={dynamicLayerError}
                  ariaLabel="気象レイヤーの表示時刻"
                />
              </div>
            )}
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

          {locateError && <p className={styles.locateError}>{locateError}</p>}
        </div>
      </div>

      {/* モバイル: サイドバーの全面ドロワーだった旧UIを、下部タブバー＋部分シート3枚へ置換
          （モバイル実機フィードバック対応T34）。改善計画T300: 「ルート詳細」パネルが
          RouteSettingsPanel・RouteList・ComparisonPanel・色分け設定を1枚に同居させ縦長に
          なっていたという実機フィードバックを受け、「ルート設定」「ルート結果」の2タブへ
          分割した。空いた枠は増やさず、情報量の薄かった「開発者」タブ（廃止、地図データ
          再読み込みは地図の見え方タブへ・デバッグログはヘッダーアイコンへ移設）の枠を使う
          ため、タブ総数は3のまま変わらない。各タブはアイコン+1行ラベル（地図上のiconChip、
          MapOverlayControls.module.cssと同じ構成）。「ルート結果」タブには、設定変更後
          未反映（conditionsDirty）を分割前と同じくタブを開かなくても気づけるよう、
          小さいバッジを付ける（完了条件(c)）。シート表示中も地図の上側が見えたまま
          パン/ズームできる（暗幕なし、詳細はBottomSheetのコメント参照）。 */}
      {isMobile && (
        <>
          <nav className={styles.mobileTabBar} aria-label="パネル切り替え">
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
              {conditionsDirty && (
                <span
                  aria-hidden="true"
                  className="absolute right-[0.6rem] top-[0.35rem] h-[0.5rem] w-[0.5rem] rounded-full bg-[var(--color-warning-strong)]"
                />
              )}
            </button>
            <button
              type="button"
              aria-pressed={mobileSheet === "map"}
              onClick={() => handleMobileTabClick("map")}
              className={mobileSheet === "map" ? `${styles.tabButton} ${styles.tabButtonActive}` : styles.tabButton}
            >
              <MapAppearanceIcon />
              <span className={styles.tabLabel}>地図の見え方</span>
            </button>
          </nav>

          <BottomSheet
            open={mobileSheet === "routeSettings"}
            onClose={() => setMobileSheet(null)}
            title="ルート設定"
            titleId={ROUTE_SETTINGS_SHEET_TITLE_ID}
            heightVh={mobileSheetHeightVh}
            onHeightChange={handleMobileSheetHeightChange}
            onHeightCommit={commitMobileSheetHeight}
          >
            {renderRouteSettingsSectionBody()}
          </BottomSheet>

          <BottomSheet
            open={mobileSheet === "routeOutcome"}
            onClose={() => setMobileSheet(null)}
            title="ルート結果"
            titleId={ROUTE_OUTCOME_SHEET_TITLE_ID}
            heightVh={mobileSheetHeightVh}
            onHeightChange={handleMobileSheetHeightChange}
            onHeightCommit={commitMobileSheetHeight}
          >
            {renderRouteOutcomeSectionBody()}
          </BottomSheet>

          <BottomSheet
            open={mobileSheet === "map"}
            onClose={() => setMobileSheet(null)}
            title="地図の見え方"
            titleId={MAP_SETTINGS_SHEET_TITLE_ID}
            heightVh={mobileSheetHeightVh}
            onHeightChange={handleMobileSheetHeightChange}
            onHeightCommit={commitMobileSheetHeight}
          >
            {renderMapSettingsSectionBody()}
          </BottomSheet>
        </>
      )}
    </div>
  );
}
