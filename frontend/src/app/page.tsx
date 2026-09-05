"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import Disclosure from "@/components/Disclosure/Disclosure";
import { Card } from "@/components/ui/Card/Card";
import { Button } from "@/components/ui/Button/Button";
import MapView from "@/components/Map/MapView";
import MapOverlayControls, { type OverlayLayerChip } from "@/components/MapOverlayControls/MapOverlayControls";
import {
  ClearAllLayersIcon,
  DownloadIcon,
  MapAppearanceIcon,
  RouteIcon,
  RouteSettingsIcon,
  SaveIcon,
} from "@/components/Map/icons";
import MapLayersPanel from "@/components/MapLayersPanel/MapLayersPanel";
import BottomSheet, { clampSheetHeightVh, DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import {
  buildMapLayers,
  buildRoadSurfaceSharedLayerIds,
  deriveFetchLayerStatus,
  isAxisStudioLayer,
  type LayerDataStatus,
  type LayerDataStatusByLayer,
  type MapLayerId,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import { RAMP_AXES, axisMapLayerId, buildAxisRampLegend } from "@/components/Map/axisLayers";
import { dedicatedWayValueLegend, type DedicatedWayValueDisplay } from "@/components/Map/dedicatedWayValueLayer";
import LensControl, { type LensOption } from "@/components/LensControl/LensControl";
import type { LegendEntry } from "@/components/Map/legendFilter";
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
  LENS_DIFFICULTY_ID,
  LENS_NONE_ID,
  getRouteStyleMode,
  isRouteStyleModeId,
  type LensId,
} from "@/components/Map/routeStyleModes";
// 「ルート設定」見出し（renderRouteSectionBody）の見た目に、MapLayersPanel側の既存
// スタイルをそのまま再利用する（CSS Modulesはクラス名の対訳表を返すだけのため、別
// コンポーネントからのimportでも問題なく使える。同じ見た目のUIをここだけのために複製
// しない）。
import layerPanelStyles from "@/components/MapLayersPanel/MapLayersPanel.module.css";
import ErrorText from "@/components/ErrorText/ErrorText";
import RouteForm, { type DestinationButtonState, type RouteMode } from "@/components/RouteForm/RouteForm";
import { useRouteFormSubmit } from "@/components/RouteForm/useRouteFormSubmit";
import RouteSettingsPanel, {
  DEFAULT_HARD_FILTERS,
  stackBarColorForIndex,
} from "@/components/RouteSettingsPanel/RouteSettingsPanel";
import RouteAxisProfile from "@/components/RouteAxisProfile/RouteAxisProfile";
import AxisContributionBar from "@/components/RouteAxisProfile/AxisContributionBar";
import WeatherPanel from "@/components/WeatherPanel/WeatherPanel";
import TodayOutlook from "@/components/TodayOutlook/TodayOutlook";
import WarningBadgeList from "@/components/WarningBadge/WarningBadge";
import HeaderMenu from "@/components/HeaderMenu/HeaderMenu";
import RideConditionBar from "@/components/RideConditionBar/RideConditionBar";
import TravelBearingControl from "@/components/TravelBearingControl/TravelBearingControl";
import { PRECIPITATION_INTENSITY_LEVELS } from "@/components/Map/precipitationNowcast";
import { WIND_SPEED_LEGEND_LEVELS, type MapViewport } from "@/components/Map/windLayer";
import { THUNDER_ACTIVITY_LEVELS, TORNADO_POTENTIAL_LEVELS } from "@/components/Map/thunderNowcast";
import { RISK_LEVEL_COLORS } from "@/components/Map/riskMap";
import { useDynamicWeatherLayers } from "@/hooks/useDynamicWeatherLayers";
import { useDynamicWayValues } from "@/hooks/useDynamicWayValues";
import { gradientGridCellsFromTileResponses } from "@/components/Map/gradientGridFill";
import { useWeatherConditions } from "@/hooks/useWeatherConditions";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { useMaterialCatalog } from "@/hooks/useMaterialCatalog";
import { syncRoutePreferenceKeys } from "@/lib/routePreferenceSync";
import { DEFAULT_ROUTE_PREFERENCE } from "@/lib/evaluationAxes";
import { formatMaterialValue, materialCatalogLabel } from "@/lib/axisMaterialsCatalog";
import { downloadGpx } from "@/lib/gpxExport";
import ComparisonPanel from "@/components/ComparisonPanel/ComparisonPanel";
import DebugConsole from "@/components/DebugConsole/DebugConsole";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { debugLog } from "@/lib/debugLog";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useElementHeightCssVar } from "@/hooks/useElementHeightCssVar";
import { useLocation } from "@/hooks/useLocation";
import { useStoredState, useStoredJsonState } from "@/hooks/useStoredState";
import { generateRoutes, type GenerationProgress } from "@/services/routeApi";
import type {
  Coordinates,
  HardFilterOverride,
  RouteCandidate,
  RoutePreferenceWeights,
  SelectedRouteSegment,
} from "@/types/route";
import { EXPERIMENT_SLOT_COLORS, MAX_EXPERIMENT_SLOTS, type ExperimentSlot } from "@/types/experimentSlot";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import styles from "./page.module.css";

const DISTANCE_TOLERANCE_KM = 5;

// 改善計画T364/T365（旧RouteList.tsxから移設）: 経由地ルートのid（常に1件、「方位」という
// 概念が無いためタブに順位番号を付けない）。
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

// 「地図の見え方」（系統B）の設定はすべてlocalStorageへ保存し、リロード後も復元する。
// 生成条件（系統A: 出発地点・距離・重み）は保存しない方針（毎回現在地・既定値から始める）。
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
const MAP_SETTINGS_OPEN_STORAGE_KEY = "ridecompass:map-settings-open";
// モバイル下部シート（「ルートを作る」/「地図の見え方」）の高さ。2シートは排他表示のため
// 1つの値を共有する（BottomSheetのheightVh props参照）。
const MOBILE_SHEET_HEIGHT_STORAGE_KEY = "ridecompass:mobile-sheet-height-vh";

// ramp軸（軸スタジオで増減しうる動的レイヤー）を除いた、ビルド時から固定のレイヤー集合の
// 既定値。DEFAULT_LAYER_VISIBILITY（静的フォールバック全体）と、useStoredStateの
// deserialize（下記）がaxisCatalog.loaded===true時に組み立てる「実行時カタログ由来の
// キー集合」の両方が、この固定部分を共通の土台として使う。
const FIXED_LAYER_VISIBILITY_DEFAULTS: Omit<MapLayerVisibility, `axis:${string}`> = {
  elevation: false,
  // 「道路情報」（road）は論理2レイヤー（roadType/roadSurface）。旧保存値（road:
  // boolean）からの移行処理はuseStoredStateのdeserialize（下記）参照。
  roadType: false,
  roadSurface: false,
  designation: false,
  tunnel: false,
  oneway: false,
  stopPoi: false,
  supplyPoi: false,
  accidents: false,
  // 降水ナウキャスト。初期表示から地図を覆うと視界を圧迫するため既定OFF（設計原則12、
  // 他の静的レイヤーと同じ「明示的にONにして初めて出る」規約）。
  precipitationNowcast: false,
  // 風の矢印。precipitationNowcastと同じ理由で既定OFF。
  windVector: false,
  // way_id→wind_drag_ratio配信層（評価軸としての風）。同じ理由で既定OFF。
  windAxis: false,
  // 環境グループの勾配gridFill・way_id→勾配配信層。同じ理由で既定OFF。
  gradientFill: false,
  gradientAxis: false,
  // 災害（雷・竜巻・落雷・キキクル4種）。他の気象レイヤーとは異なり既定ONにする——
  // 防災級の情報はユーザー操作を待たず表示すべき（予兆があってからチップをONにするのでは
  // 手遅れ）という理由で、チップというUI要素は持たせつつ既定表示にしておく。危険度ゼロの
  // 領域は配信元のタイルが透明のため、平常時の地図の見た目は変わらない。
  disaster: true,
  // 線状降水帯予測マップはrasrf系統（降水短時間予報と同じ）のため「降水」チップの傘下へ
  // 統合されており、個別のlayerVisibilityキーを持たない（frontend/src/hooks/
  // useDynamicWeatherLayers.ts参照）。
  route: true,
};

const DEFAULT_LAYER_VISIBILITY: MapLayerVisibility = {
  ...FIXED_LAYER_VISIBILITY_DEFAULTS,
  // 二次軸rampレイヤー。backendレジストリ生成物（axis-catalog.json）のkind="ramp"軸から
  // 自動生成されるため、個別の行を手書きせずカタログから導出する
  // （新しい軸が増えてもこのファイルの編集は不要）。既定はすべてOFF。
  // これは実行時カタログ未取得時の静的フォールバック（RAMP_AXES＝axisLayers.tsのビルド時
  // スナップショット）であり、軸スタジオで新規公開された軸のキーはここには含まれない
  // （フェッチ完了後の扱いはuseStoredStateのdeserialize、下記参照）。
  ...Object.fromEntries(RAMP_AXES.map((axis) => [axisMapLayerId(axis.axisId), false])),
};

// 「どのモードでも非表示カテゴリ無し」を表す共通の空配列。useStateの外に置いて参照を
// 固定し、MapView側のエフェクト依存（hidden*LegendKeys）が毎レンダーで発火しないようにする。
const NO_HIDDEN_LEGEND_KEYS: string[] = [];

// 降水ナウキャスト・風の凡例。地図チップの▶パネル（MapOverlayControls:
// renderLegendDetails）は表示専用でLegendEntry.filterを実際には適用しない（道路種別等の
// ようなカテゴリ絞り込みができるレイヤーではないため）ため、filterは一致することのない
// ダミー値にしている。色・階級の実データはprecipitationNowcast.ts/windLayer.ts側
// （実際の描画・凡例双方の単一の情報源）から持ってくる。他レイヤーと違い絞り込み状態を
// 持たないため、useMemoではなくモジュール直下の固定値でよい。
const UNUSED_LEGEND_FILTER: unknown[] = ["==", 1, 0];
// 線状降水帯予測マップは「降水」チップの傘下（4つ目のソース）へ統合されているため、
// 専用の凡例ブロックを`accidents`の「当事者/重大度」と同じ複数ブロックパターンで
// このPRECIPITATION_LEGEND_DETAILS自体へ追加する（実データはriskMap.tsが単一の情報源）。
const PRECIPITATION_LEGEND_DETAILS: LegendFilterSummaryAxis[] = [
  {
    label: "",
    legend: PRECIPITATION_INTENSITY_LEVELS.map((level) => ({ ...level, filter: UNUSED_LEGEND_FILTER })),
    hiddenKeys: NO_HIDDEN_LEGEND_KEYS,
  },
  {
    label: "線状降水帯予測マップ（現在〜3時間先のみ）",
    legend: [{ key: "linearRainband", label: "今後3時間以内に大雨のおそれ", color: "#ff0000", filter: UNUSED_LEGEND_FILTER }],
    hiddenKeys: NO_HIDDEN_LEGEND_KEYS,
  },
];
// この凡例は矢印（風速そのもの、向きに依存しない）の配色専用で、道路の色分け（windAxis、
// 走行方位に対する向かい風/追い風）とは別の配色系統のため、「地図の色の凡例」との混同を
// 避けて「矢印（風速）」と明示する。
const WIND_LEGEND_DETAILS: LegendFilterSummaryAxis[] = [
  {
    label: "矢印（風速）",
    legend: WIND_SPEED_LEGEND_LEVELS.map((level) => ({ ...level, filter: UNUSED_LEGEND_FILTER })),
    hiddenKeys: NO_HIDDEN_LEGEND_KEYS,
  },
];
// 災害チップの要素トグルの保存先ID（hiddenLegendKeysByModeのキー）。実際の絞り込み軸
// （路面の種類等）のIDと衝突しないよう、レイヤーIDそのものを使う。
const DISASTER_SOURCE_AXIS_ID = "disaster";

// 災害チップの▶パネルに出す「表示する情報」（7要素の個別トグル）。axisIdを持つため
// LegendCheckboxListで描画され、非表示キーはhiddenLegendKeysByMode[DISASTER_SOURCE_AXIS_ID]
// へ保存される（サイドバーの絞り込みと同じ保存先・同じ操作感）。keyは
// DYNAMIC_WEATHER_RENDERERSのdisasterグループのソースキーと一致させる必要がある
// （useDynamicWeatherLayersがこのkeyでソースごとのvisibleを決めるため）。
// 面同士は重なると混色して危険度を読み取れないため、混んできたらここで絞り込む。
const DISASTER_SOURCE_LEGEND: LegendEntry[] = [
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
const MAP_SETTINGS_SECTION_TITLE_ID = "map-settings-section-title";
// 候補タブ列のvalue体系: 候補はroute id、比較は"comparison"、先頭固定の「保存済み」は
// SAVED_ROUTES_TAB_VALUE（保存機能の実装まではタブ自体を描画しない）。
const SAVED_ROUTES_TAB_VALUE = "saved";
// モバイルの「地図の見え方」シート見出しのDOM id。
const MAP_SETTINGS_SHEET_TITLE_ID = "map-settings-sheet-title";
// モバイルの「ルート設定」「ルート結果」シート見出しのDOM id。
const ROUTE_SETTINGS_SHEET_TITLE_ID = "route-settings-sheet-title";
const ROUTE_OUTCOME_SHEET_TITLE_ID = "route-outcome-sheet-title";

type MobileSheet = "routeSettings" | "routeOutcome" | "map" | null;

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
  const handleWaypointAdd = useCallback((point: Coordinates) => {
    setWaypoints((prev) => [...prev, point]);
  }, []);
  const handleWaypointRemove = useCallback((index: number) => {
    setWaypoints((prev) => prev.filter((_, i) => i !== index));
  }, []);
  const handleWaypointsClear = useCallback(() => setWaypoints([]), []);

  // 目的地（最大1点）。指定時は起点に戻らず目的地で終わる片道ルートになる
  // （handleGenerate参照）。destinationArmedは「目的地を設定」ボタン押下から次の1タップ
  // までの間だけtrueになり、地図クリックが目的地配置として扱われる（MapView.tsx参照）。
  const [destination, setDestination] = useState<Coordinates | null>(null);
  const [destinationArmed, setDestinationArmed] = useState(false);

  // 周回（距離指定）/目的地（地図タップで経由地・目的地を指定）モードの切り替え。
  // 経由地・目的地の操作はRouteForm（距離入力・生成ボタンと同じ場所）に統合されている。
  // モード切り替え自体は経由地・目的地の値を消さない（周回モードへ切り替えても地図上のピンは
  // 保持し、目的地モードへ戻れば復元される。地図への表示・追加受付だけがモードで変わる、
  // handleGenerate/MapView.tsxのpinPlacementEnabled参照）。
  const [routeMode, setRouteMode] = useState<RouteMode>("loop");
  const handleRouteModeChange = useCallback(
    (mode: RouteMode) => {
      setRouteMode(mode);
      if (mode === "destination") {
        // 目的地・経由地とも未指定のまま目的地モードへ入った場合、ゴールアイコンを
        // 押さなくても次のタップで即座に目的地を指定できるようにする。既に目的地・
        // 経由地があるときは自動武装しない——次のタップの意図が「経由地の追加」である
        // 可能性があり、武装したままだと意図せず目的地が上書きされてしまうため。
        setDestinationArmed(destination === null && waypoints.length === 0);
      } else {
        // 武装中に周回モードへ切り替えた場合、目的地モードへ戻るまで武装状態を持ち越さない。
        setDestinationArmed(false);
      }
    },
    [destination, waypoints.length]
  );

  const handleDestinationSet = useCallback((point: Coordinates) => {
    setDestination(point);
    setDestinationArmed(false);
  }, []);
  const handleDestinationClear = useCallback(() => setDestination(null), []);
  // ボタン1個で「未設定→武装→設定済み→解除」を一巡させる。武装中に同じボタンを押すと
  // キャンセルできる。
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
  // 出すため。
  const [distanceInput, setDistanceInput] = useState("30");
  // 周回候補の上限件数（backend: RouteGenerateRequest.max_routes、1〜15）。距離入力と
  // 同じくstring stateのまま保持し、送信時にNumber化する。目的地モードでは経由地が無い
  // 場合のみ意味を持つ（経由地を伴うとbackendが常に1件へ固定し無視する、RouteForm.tsx参照）。
  const [maxRoutesInput, setMaxRoutesInput] = useState(String(routeGenerateConfig.default_max_routes));
  // 「ルート生成」ボタン（「ルート設定」見出し行、RouteForm.tsxのタブとは別位置）の
  // 検証・送信ロジック。handleGenerateは関数宣言のため巻き上げにより以降で定義されていても
  // 参照できる。
  const routeFormSubmit = useRouteFormSubmit({
    distance: distanceInput,
    maxRoutes: maxRoutesInput,
    routeMode,
    waypointCount: waypoints.length,
    destinationState,
    onGenerate: handleGenerate,
  });
  // 仮定巡航速度（backend: RouteGenerateRequest.assumed_speed_kmh、km/h）。距離と同じく
  // string stateのまま保持し、送信時にNumber化する。区間の通過予定時刻（探索時の風の時刻
  // 選択）・到達予想時刻の基準になるため全モードで送る。
  const [assumedSpeedKmh, setAssumedSpeedKmh] = useState<number>(routeGenerateConfig.default_assumed_speed_kmh);
  // 表示中の候補を生成したときの条件スナップショット。重みは値の組をJSON文字列で比較する
  // （フィールド比較の列挙より差分検知の漏れが出にくい）。
  const [generatedConditions, setGeneratedConditions] = useState<{
    latitude: number;
    longitude: number;
    distanceKm: number;
    maxRoutes: number;
    assumedSpeedKmh: number;
    // 候補件数入力が生成結果に反映される条件だったか（周回モード、または経由地の無い
    // 目的地モード）。経由地を伴う目的地モードはbackendが件数を無視するため、
    // conditionsDirtyの比較対象から外す。
    maxRoutesRelevant: boolean;
    weightsKey: string;
    // 目的地モードで生成した場合はdistanceKmが地図上のピンからの自動算出値になり、
    // distanceInput（RouteFormが表示しない値）とは無関係になるため、conditionsDirtyの
    // 距離比較はloopモードで生成したときだけ行う。
    routeMode: RouteMode;
    // 目的地モードで生成した経由地・目的地のスナップショット（JSON文字列化して比較、
    // weightsKeyと同じ方式）。生成後に経由地を追加・削除・移動した変更もconditionsDirtyが
    // 検知できるようにする。
    waypointsKey: string;
    // 経由地の無い目的地ルートで、指定した目的地がメインの道路網から孤立していたため
    // backendが最寄りのアクセス可能な地点へ補正した場合true
    // （conditions.corrected_destination）。表示中の候補がこの補正を経て生成された
    // ことを示すヒントの表示条件に使う。
    destinationCorrected: boolean;
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
  const [weightOverrideEnabled, setWeightOverrideEnabled] = useStoredJsonState(
    "ridecompass:weight-override-enabled",
    false
  );
  const [routePreference, setRoutePreference] = useStoredJsonState<RoutePreferenceWeights>(
    "ridecompass:route-preference",
    DEFAULT_ROUTE_PREFERENCE
  );
  // 0次ハードフィルタ。一般向けルート設定画面（RouteSettingsPanel）が
  // 常時操作するため、weightOverrideEnabledのような別トグルは持たず常にリクエストへ含める
  // （既定値はDEFAULT_HARD_FILTERS＝backendのDEFAULT_HARD_FILTERSと同じ全フィルタ有効で、
  // 省略時と挙動が一致するため常時送信して問題ない）。
  const [hardFilters, setHardFilters] = useState<HardFilterOverride>(DEFAULT_HARD_FILTERS);

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

  // MapViewから伝わる現在のビューポート（改善計画T180、MapView.tsx: onViewportChange参照）。
  // moveend/zoomendのたびに素の値が来るため、フェッチ用にはデバウンスして使う
  // （useDynamicWeatherLayers/useWeatherGrid内のwindDetailフェッチeffect参照）。
  const [mapViewport, setMapViewport] = useState<MapViewport | null>(null);

  // 地図レイヤーのON/OFF（MAP_LAYERSのid単位。レイヤーを追加したらDEFAULT_LAYER_VISIBILITYへ
  // 初期値を1つ足す）。localStorageへの保存・復元はuseStoredState参照。既知のレイヤーID
  // かつboolean値のものだけ採用する（レイヤーの増減や壊れた保存値があっても、残りの設定は
  // 活かしてデフォルトで埋める）。
  //
  // axisCatalog.loadedを見て、未フェッチ時はビルド時静的軸集合（DEFAULT_LAYER_VISIBILITY）、
  // フェッチ完了後は実行時カタログ（axisCatalog.rampAxes）ベースのキー集合を走査する
  // ことで、軸スタジオで新規公開された軸（axis:xxx等）のON/OFF保存値も復元できる。
  // reloadKeyにaxisCatalog.loadedを渡すことで、マウント直後（静的集合で復元）→
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
      axisCatalog.secondaryAxes.filter((axis) => {
        if (!axis.layerId) return false;
        return primaryAttributeIdsToLayerIds(axis.primaryAttributeIds).some((materialId) => layerVisibility[materialId]);
      }).map((axis) => axis.layerId as MapLayerId),
    [layerVisibility, axisCatalog.secondaryAxes],
  );
  // レンズ（地図を何で塗るか）: "none" | "difficulty" | 公開軸のaxis_id。ルート前は全道路
  // （rampタイル・専用配信）、ルート後はルート線を同じ識別子で塗る。生成・クリア・候補切替を
  // またいで保持する。保存形式はJSON化しない生文字列（isRouteStyleModeIdによる妥当性検証が
  // JSON.parseを兼ねる）。軸スタジオでunpublishされた軸idは総合難易度へ倒す。
  const [lens, setLens] = useStoredState<LensId>(
    ROUTE_STYLE_MODE_STORAGE_KEY,
    DEFAULT_ROUTE_STYLE_MODE_ID,
    { serialize: (v) => v, deserialize: (raw) => (isRouteStyleModeId(axisCatalog.routeStyleModes, raw) ? raw : null) },
  );
  const routeStyleModes = axisCatalog.routeStyleModes;
  useEffect(() => {
    if (routeStyleModes.some((mode) => mode.id === lens)) return;
    debugLog(
      "map:route-style-mode",
      `lens "${lens}" is not a known axis id, falling back to "${LENS_DIFFICULTY_ID}"`,
      { requestedId: lens, availableIds: routeStyleModes.map((mode) => mode.id) },
      "warn"
    );
    setLens(LENS_DIFFICULTY_ID);
  }, [routeStyleModes, lens, setLens]);
  // ルート確定後も周囲の道路（全道路の塗り）を残すか。
  const [lensKeepAfterRoute, setLensKeepAfterRoute] = useStoredState<boolean>(LENS_KEEP_AFTER_ROUTE_STORAGE_KEY, true, {
    serialize: (v) => JSON.stringify(v),
    deserialize: (raw) => (raw === "true" ? true : raw === "false" ? false : null),
  });
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
  const [outcomeOpen, setOutcomeOpen] = useStoredState(OUTCOME_OPEN_STORAGE_KEY, true, {
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
  const [mapSettingsOpen, setMapSettingsOpen] = useStoredState(MAP_SETTINGS_OPEN_STORAGE_KEY, true, {
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
  const hasDetail = !!selectedCandidate?.segments && selectedCandidate.segments.length > 0;

  const isMobile = useIsMobile();

  // 地図上の▼ページ送り判定（MapOverlayControls.tsx: usePagedOverflow）が、兄弟要素として
  // 重なる気象タイムラインパネル（下記.bottomControlRow）の占有高さを知らず、パネル表示中に
  // 一番下のアイコンチップがパネルの裏へ隠れてしまう不具合への対応。共通の祖先（.mapPane）へ
  // 実測高さをCSS変数として反映し、MapOverlayControls.module.cssの.wrapper側で読む。
  const mapPaneRef = useRef<HTMLDivElement>(null);
  const bottomControlRowRef = useRef<HTMLDivElement>(null);
  useElementHeightCssVar(bottomControlRowRef, mapPaneRef, "--bottom-control-row-height");

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
  // このファイル自身の凡例・絞り込みサマリ計算（staticLegendHiddenKeysByAxis・
  // staticFilterSummaries、下記）は、軸スタジオで新規公開したramp軸の凡例・絞り込み
  // 操作をこの画面のサマリ表示・MapLayersPanelへ反映できるよう、mapLayers/
  // roadSurfaceSharedLayerIdsと同じくaxisCatalog.rampAxesから都度組み立てる
  // （ビルド時静的STATIC_FILTER_AXESは使わない）。
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
  // 道路情報・道路情報以外の絞り込み可能レイヤーの「すべて表示/すべて隠す」一括操作
  // （1軸分の非表示キー全体の置き換え）。個別チェックはtoggleHiddenLegendKeyをそのまま使う
  // （絞り込みは即時反映、T31。レイヤーの自動ONはMapLayersPanel側が担う）。
  // 改善計画T468: 実装（setHiddenLegendKeysByModeの更新ロジック）自体はこの1箇所へまとめ、
  // 呼び出し側の型（RoadFilterAxisId/StaticFilterAxisId）だけを分けたラッパーを2つ持つことで、
  // 実装の重複を無くしつつ誤った軸idの取り違えを防ぐ型安全性は維持する。
  const setHiddenLegendKeysForAxis = useCallback(
    (axisId: string, hiddenKeys: string[]) => {
      setHiddenLegendKeysByMode((prev) => ({ ...prev, [axisId]: hiddenKeys }));
    },
    [setHiddenLegendKeysByMode],
  );
  const handleRoadAxisSetHidden = useCallback(
    (axisId: RoadFilterAxisId, hiddenKeys: string[]) => setHiddenLegendKeysForAxis(axisId, hiddenKeys),
    [setHiddenLegendKeysForAxis],
  );
  const handleStaticFilterAxisSetHidden = useCallback(
    (axisId: StaticFilterAxisId, hiddenKeys: string[]) => setHiddenLegendKeysForAxis(axisId, hiddenKeys),
    [setHiddenLegendKeysForAxis],
  );
  const handleRouteLegendToggle = useCallback(
    (key: string) => toggleHiddenLegendKey(lens, key),
    [lens, toggleHiddenLegendKey],
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
  // 軸スタジオの公開軸を含む）から組み立てたレイヤーカタログを使う。handleLayerToggle
  // （直下）が排他ドメイン判定のためmapLayers全体を参照するため、overlayLayers組み立て
  // （後方）より前で定義する。
  const mapLayers = useMemo(() => buildMapLayers(axisCatalog.rampAxes), [axisCatalog.rampAxes]);
  const roadSurfaceSharedLayerIds = useMemo(
    () => buildRoadSurfaceSharedLayerIds(axisCatalog.rampAxes),
    [axisCatalog.rampAxes]
  );

  // 「推定指標をONにすると材料の観測データレイヤーも連動ON」するカスケードは持たない。
  // 観測グループのメンバーを個別に「表示項目の設定」で非表示にできるため、非表示にした
  // メンバーが推定指標側の操作で裏からONにされてしまうと、非表示設定でチップ自体が
  // 隠れているためユーザーがOFFに戻す手段を失う（「チップからは消えたのに地図には出続ける」
  // 不整合が起きる）。推定軸の材料がどれか（どの観測データが計算に使われているか）は
  // `renderMaterialsNote`（MapOverlayControls.tsx）が▼展開時に「材料: ○○」として常に
  // 示すため、連動ONで自動的に地図へ出す必要性は薄い。
  //
  // 地図上チップ（道路/環境/スポット）はどれも複数同時にONにできる。重なって読みにくく
  // なった場合は、各チップの▶パネルで要素・カテゴリ単位に絞り込む
  // （MapOverlayControls.tsx: renderLegendDetails）。道路グループの線同士は
  // `line-offset`による並行トラック（MapView.tsx: applyRoadMaterialTrackOffsets）で
  // 重ならずに並ぶ。
  //
  // 軸スタジオ由来のレイヤー（isAxisStudioLayer、ramp軸・windAxis・gradientAxis）だけは
  // 1つだけ選べる状態を保つ。これらは同じ道路の同じ位置をそれぞれの評価で塗り分けるため、
  // 重ねると後から描画した色が前の色を完全に覆い、並行トラックのように並べて見ることも
  // できない（地図上チップではなくルート設定パネル・レンズから操作する）。
  const handleLayerToggle = useCallback(
    (id: MapLayerId, on: boolean) => {
      setLayerVisibility((prev) => {
        const next: MapLayerVisibility = { ...prev, [id]: on };
        if (on) {
          const layer = mapLayers.find((l) => l.id === id);
          if (layer && isAxisStudioLayer(layer)) {
            for (const other of mapLayers) {
              if (other.id === id) continue;
              if (isAxisStudioLayer(other)) next[other.id] = false;
            }
          }
        }
        return next;
      });
    },
    [setLayerVisibility, mapLayers],
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

  // 地図上（MapOverlayControls）のサマリ行に出す「適用中の条件」の1行要約。改善計画T165で
  // 「道路情報」は路面の種類（roadSurface）・道路の種類（roadType）の論理2レイヤーの
  // ため、軸ごとに個別のサマリ・内訳を持つ。ズーム不足の案内は絞り込みより優先する
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
              axisId: roadSurfaceAxis.id,
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
            {
              label: "",
              legend: roadTypeAxis.legend,
              hiddenKeys: roadHiddenKeysByMode[roadTypeAxis.id] ?? NO_HIDDEN_LEGEND_KEYS,
              axisId: roadTypeAxis.id,
            },
          ],
    [regionZoomTooWide, roadTypeAxis, roadHiddenKeysByMode],
  );
  // ルートは色分けモード自体が「何の条件で色分け中か」の情報なので常に出す
  const routeSummary = hasDetail
    ? `レンズ: ${getRouteStyleMode(routeStyleModes, lens).label}${hiddenRouteLegendKeys.length > 0 ? "・一部非表示" : ""}`
    : null;
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

  // 道路情報以外の絞り込み可能レイヤーも、道路情報と同じ要約関数（summarizeLegendFilters）
  // でチップ下に適用中の絞り込みを表示する。レイヤーごとに
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
        axisId: axis.axisId,
      }));
      result[layerId] = {
        summary: summarizeLegendFilters(axes),
        legendDetails: axes,
      };
    }
    return result;
  }, [staticFilterAxes, staticLegendHiddenKeysByAxis]);

  // 動的気象レイヤー（降水ナウキャスト・風/延長降水予報・雷/竜巻ナウキャスト・キキクル）の
  // フェッチ・共有タイムライン・MapView向け描画ペイロードは`useDynamicWeatherLayers`
  // フックが持つ。各要素は対応するshow*がtrueの間だけフェッチする。overlayLayers
  // （下記）がdataStatusとして参照するため、その手前で定義する。
  const showPrecipitationNowcast = layerVisibility.precipitationNowcast;
  const showWindVector = layerVisibility.windVector;
  const showDisaster = layerVisibility.disaster;
  // 災害チップ配下の7要素のうち、▶パネルで非表示に選ばれているもの。面同士が重なると
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
  } = useDynamicWeatherLayers({
    showWindVector,
    showPrecipitationNowcast,
    showDisaster,
    hiddenDisasterSources,
    mapViewport,
  });
  // レイヤーごとのデータ取得状態を1つに統合する。mapViewLayerDataStatus（MapLibreの
  // ソースイベントから算出）とdynamicWeatherDataStatus（動的気象レイヤー、フェッチ
  // 自身のloading/errorから算出）はキーが重ならない（動的気象レイヤーは
  // buildLayerDataSourcesの対象外）ため、マージの優先順位を気にする必要はない。
  const layerDataStatus = useMemo<LayerDataStatusByLayer>(
    () => ({ ...mapViewLayerDataStatus, ...dynamicWeatherDataStatus }),
    [mapViewLayerDataStatus, dynamicWeatherDataStatus]
  );

  // 地図上のチップ行はレイヤーカタログ（mapLayers）から組み立てる。レイヤーを追加したら
  // summaryの対応をここへ1行足すだけでよい（チップ・凡例パネルの描画は汎用）。
  const overlayLayers = useMemo<OverlayLayerChip[]>(() => {
    // summary/legendDetailsはlayer.id→値のルックアップで組み立て、無ければ
    // staticFilterSummariesをフォールバックとして最後に見る。
    const summaryByLayerId: Partial<Record<MapLayerId, string | null>> = {
      roadSurface: roadSurfaceSummary,
      roadType: roadTypeSummary,
      route: routeSummary,
    };
    const legendDetailsByLayerId: Partial<Record<MapLayerId, LegendFilterSummaryAxis[]>> = {
      roadSurface: roadSurfaceLegendDetails,
      roadType: roadTypeLegendDetails,
      route: routeLegendDetails,
      precipitationNowcast: PRECIPITATION_LEGEND_DETAILS,
      windVector: WIND_LEGEND_DETAILS,
      disaster: disasterLegendDetails,
    };
    return mapLayers.map((layer) => {
        // windAxis（way_id→wind_drag_ratio配信層）・ramp軸（axis:${string}）は
        // isAxisStudioLayerによりMapOverlayControls自体がチップとして描画しない
        // （評価軸はルート設定パネルへ移設済み、mapLayers.ts参照）ため、このoverlayLayers
        // 配列に含めるのは「全レイヤー一括OFF」ボタン（handleClearAllLayers、下記）が
        // layerVisibilityへ引き続きアクセスできるようにするためだけの目的になった。
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
        const summary = layer.id in summaryByLayerId
          ? (summaryByLayerId[layer.id] ?? null)
          : (staticFilterSummaries[layer.id]?.summary ?? null);
        const legendDetails =
          legendDetailsByLayerId[layer.id] ?? staticFilterSummaries[layer.id]?.legendDetails;
        // 動的グループ（降水ナウキャスト・風・雷・竜巻）は絞り込み機能を持たないため
        // 「地図の見え方」パネルの行自体を持たない（MapLayersPanel.tsx参照）。地図上チップの
        // ▶パネル本体には説明文を常時表示せず、凡例のみを表示する。折りたたみ中の
        // 「表示する項目を選ぶ」設定パネル（MapOverlayControls.tsx: renderVisibilitySettings）
        // 側は、各メンバー行に個別の情報アイコンを置き、押したメンバーだけ説明文を表示する
        // （panelHintは推定/観測/動的の全メンバーへ渡すが、常時表示にはしない）。
        // 「動的グループ」の判定はmapLayers.ts側の単一ソースdataNature==="dynamic"を見る
        // （layer.idのハードコード列挙ではなく、この基準に揃えることで新規レイヤーが
        // 増えても追従する）。
        const isDynamicGroupLayer = layer.dataNature === "dynamic";
        return {
          id: layer.id,
          label: layer.label,
          chipLabel: layer.chipLabel ?? layer.label,
          on: layerVisibility[layer.id],
          disabled,
          // 動的グループはサイドバーに設定行が無くなったため「[設定はサイドバー]」を付けない。
          title:
            disabledReason ??
            (isDynamicGroupLayer ? layer.description : `${layer.description}[設定はサイドバー]`),
          summary,
          legendDetails,
          // 地図上チップのカテゴリ束ね（MapOverlayControls.tsx）用。
          category: layer.category,
          dataNature: layer.dataNature,
          // 「表示する項目を選ぶ」設定パネルの個別情報アイコン用の説明文。
          panelHint: layer.panelHint,
          // レイヤーのデータ取得状態。LayerChip（サイドバー）と同じくOFF中の抑制は
          // ChipButton自身が`active && dataStatus != null`で行うため、ここでは
          // layerVisibilityで抑制せずそのまま渡す。
          dataStatus: layerDataStatus[layer.id],
        };
      });
  }, [
    selectedCandidate,
    layerVisibility,
    layerDataStatus,
    roadSurfaceLegendDetails,
    roadSurfaceSummary,
    roadTypeLegendDetails,
    roadTypeSummary,
    routeLegendDetails,
    routeSummary,
    staticFilterSummaries,
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
    (sheet: "routeSettings" | "routeOutcome" | "map") => {
      setMobileSheet((prev) => (prev === sheet ? null : sheet));
      // 「ルート結果」タブを開いたら、新着結果の合図は役目を終える。
      if (sheet === "routeOutcome") setHasUnseenResults(false);
    },
    [setMobileSheet]
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

  // MapViewからのビューポート通知（MapView.tsx: onViewportChange参照）。
  const handleViewportChange = useCallback((viewport: MapViewport) => {
    setMapViewport(viewport);
  }, []);

  // 今日の見通し（TodayOutlook向け、Open-Meteo予報）・最寄りアメダス実測値（WeatherPanel＝
  // 常設ヘッダー向け）・警告バッジ3種（JMA警報・注意報／WBGT／河川氾濫予報）のフェッチ・
  // 状態管理（useWeatherConditionsが持つ。weather[Open-Meteo]とamedas[アメダス実測]は
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
  } = useWeatherConditions(location, locationReady);

  // 動的材料の状態別表現契約の[時刻,向き]のうち「向き」は、風・勾配で単一の共有state
  // （travelBearingDeg、実際の進行方向という1つの概念を表す）を使う。「環境」グループの
  // 勾配gridFill・評価軸としての風/勾配（windAxis/gradientAxis）のいずれもこの1つの値を
  // 共有する。設定UIは地図上のTravelBearingControl（`components/TravelBearingControl/`）
  // 1箇所に集約されている。
  const [travelBearingDeg, setTravelBearingDeg] = useState(0);

  // way_id→wind_drag_ratio配信層。評価軸としての風——上のuseDynamicWeatherLayers（「環境」
  // グループの矢印表示）とは独立したフェッチだが、[時刻,向き]の入力（dynamicLayerTargetTime・
  // travelBearingDeg）は共有する。mapViewportは同じMapView.tsx: onViewportChange経由の
  // 値を共有する。
  //
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
  const showWindAxis = lens === "wind" && lensBackgroundShown;
  // 想定速度（ルート設定の入力欄）は風のレンズ（走行速度依存の材料）にも効く。未入力・不正値の
  // 間は既定速度で配信を続ける。
  const lensSpeedKmh = assumedSpeedKmh;
  const windAxisData = useDynamicWayValues(
    "wind",
    showWindAxis,
    mapViewport,
    travelBearingDeg,
    dynamicLayerTargetTime,
    lensSpeedKmh
  );

  // way_id→勾配（effective_gradient）配信層。windAxisと同型だが、勾配は時刻に依存しない
  // ためdynamicLayerTargetTimeを共有しない。向き（travelBearingDeg）は風と共有する
  // （上記の統合コメント参照）。「環境」グループ（gradientFill、gridFill面表示）・評価軸
  // としての勾配（gradientAxis）が同じ1つの入力（向き）を共有する。表示のON/OFF自体は
  // 別チップのまま。
  const showGradientFill = layerVisibility.gradientFill && !hasDetail;
  const showGradientAxis = lens === "gradient" && lensBackgroundShown;
  // 環境（面）・評価軸（線）どちらかがONの間だけフェッチする（表示中のものだけ叩く方針）。
  // gradientFillはgradientAxisとは独立に、フェッチ済みのway単位データをタイル単位で集計
  // するだけで作れる（gradientGridFill.tsのモジュールdocstring参照、追加のAPI呼び出し
  // 不要）ため、フェッチ自体は1本で両方の表現を賄う。
  const gradientAxisData = useDynamicWayValues(
    "gradient",
    showGradientAxis || showGradientFill,
    mapViewport,
    travelBearingDeg,
    undefined
  );
  const gradientFillPayload = useMemo(
    () => (showGradientFill ? gradientGridCellsFromTileResponses(gradientAxisData.byTile) : undefined),
    [showGradientFill, gradientAxisData.byTile]
  );
  // dedicatedWayValueDisplaysと同じ理由（design-principles.md構造仕様3: 軸ごとにpropを
  // 新設しない）で、axisId→(way_id→値)の汎用Mapへ統合する。useDynamicWayValues自体は
  // materialIdごとに個別インスタンス化する設計（デバウンス・レース対策がaxis間で
  // 独立している必要があるため、hooks/useDynamicWayValues.ts参照）のままで、統合するのは
  // MapViewへ渡す直前のprop形状だけ。
  const dedicatedWayValues = useMemo(
    () =>
      new Map<string, ReadonlyMap<number, number>>([
        ["wind", windAxisData.values],
        ["gradient", gradientAxisData.values],
      ]),
    [windAxisData.values, gradientAxisData.values]
  );
  // dedicatedWayValuesと同じ理由（design-principles.md構造仕様3）で、フェッチ進行中
  // フラグもaxisId→booleanの汎用Mapへ統合する（windLoading/gradientLoadingのような
  // 別名propは持たない）。MapView側はこれを使い、まだ値を受け取っていないwayを
  // 「取得中」（COLOR_LOADING）と「取得済みだが値が無い」（COLOR_NO_DATA）で塗り分ける。
  const dedicatedWayValueLoading = useMemo(
    () =>
      new Map<string, boolean>([
        ["wind", windAxisData.loading],
        ["gradient", gradientAxisData.loading],
      ]),
    [windAxisData.loading, gradientAxisData.loading]
  );
  // レンズが専用配信軸（windAxis/gradientAxis）を指している間だけ、そのフェッチの
  // loading/empty/errorをLensControlのピルへ渡す（road_surface等のT87経路
  // [useLayerDataStatus]はこれらのfetchを観測できないため、deriveFetchLayerStatusで
  // 動的気象レイヤーと同じ判定を共有する）。ramp軸・総合難易度・なしはこの失敗モードを
  // 持たないためundefinedのまま。
  const lensFetchStatus = useMemo<LayerDataStatus | undefined>(() => {
    if (showWindAxis) {
      return deriveFetchLayerStatus(
        windAxisData.loading,
        windAxisData.error ? "fetch-failed" : null,
        windAxisData.values.size > 0
      );
    }
    if (showGradientAxis) {
      return deriveFetchLayerStatus(
        gradientAxisData.loading,
        gradientAxisData.error ? "fetch-failed" : null,
        gradientAxisData.values.size > 0
      );
    }
    return undefined;
  }, [
    showWindAxis,
    showGradientAxis,
    windAxisData.loading,
    windAxisData.error,
    windAxisData.values,
    gradientAxisData.loading,
    gradientAxisData.error,
    gradientAxisData.values,
  ]);
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
        boundaries: axis.displayThresholdsOverride ?? undefined,
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
      color: axisChipColors[axis.axisId] ?? "#64748b",
      description: axis.description,
      unused: (weights[axis.axisId] ?? 0) <= 0,
      routeOnly: !rampAxisIds.has(axis.axisId) && !axis.dedicatedWayValueLayer,
    }));
  }, [axisCatalog.axes, axisCatalog.rampAxes, axisChipColors, generatedRoutePreference, routePreference]);
  // 現在のレンズの凡例。ルート後はルート線のモード凡例（段階の非表示切替つき）、ルート前は
  // ramp軸・専用配信の凡例（読み取り専用）。どちらも塗る手段が無ければ空。
  const lensLegend = useMemo<LegendEntry[]>(() => {
    if (lens === LENS_NONE_ID) return [];
    if (hasDetail) return getRouteStyleMode(routeStyleModes, lens).legend;
    const rampAxis = axisCatalog.rampAxes.find((axis) => axis.axisId === lens);
    if (rampAxis) return buildAxisRampLegend(rampAxis);
    const axis = axisCatalog.axes.find((a) => a.axisId === lens);
    if (axis?.dedicatedWayValueLayer) {
      return dedicatedWayValueLegend(dedicatedWayValueDisplays.get(lens)).map((band, index) => ({
        key: `band-${index}`,
        label: band.label,
        color: band.color,
        filter: [],
      }));
    }
    return [];
  }, [lens, hasDetail, routeStyleModes, axisCatalog.rampAxes, axisCatalog.axes, dedicatedWayValueDisplays]);

  // 生成条件のうち重み設定の比較キー（上書き無効時はnull＝バックエンド既定値を表す）。
  const currentWeightsKey = JSON.stringify({
    weights: weightOverrideEnabled ? { routePreference } : null,
    // hard_filtersは常時送信するため、上書き系のようなnull分岐を持たず常に比較対象へ
    // 含める。
    hardFilters,
  });

  // 表示中の候補の生成条件と現在のフォーム値がずれているか（生成条件系は「生成ボタンで
  // 反映」のため、編集しただけでは何も起きない。それをヒントとして可視化する）
  const conditionsDirty =
    generatedConditions != null &&
    routes.length > 0 &&
    (location.latitude !== generatedConditions.latitude ||
      location.longitude !== generatedConditions.longitude ||
      routeMode !== generatedConditions.routeMode ||
      (generatedConditions.routeMode === "loop" && Number(distanceInput) !== generatedConditions.distanceKm) ||
      (generatedConditions.maxRoutesRelevant && Number(maxRoutesInput) !== generatedConditions.maxRoutes) ||
      assumedSpeedKmh !== generatedConditions.assumedSpeedKmh ||
      (generatedConditions.routeMode === "destination" &&
        JSON.stringify({ waypoints, destination }) !== generatedConditions.waypointsKey) ||
      currentWeightsKey !== generatedConditions.weightsKey);

  async function handleGenerate(distanceKm: number) {
    setLoading(true);
    setGenerationProgress(null);
    setErrorMessage(null);
    try {
      // 送信直前にキー整合を補正する。RouteSettingsPanelがマウント済みならこの時点で
      // 既にキーは一致しており synced は null になる。axisCatalog.defaultWeights自体が
      // まだ軸スタジオの現在状態を反映していない（axisCatalog.loaded===false、未取得・
      // 取得失敗）場合、この同期は静的フォールバック（既存7軸）に合わせてroutePreferenceを
      // 書き換えてしまい、実際の公開軸集合とは無関係な値になる。この場合はroute_preference
      // 自体を省略し、backend側の既定値（load_route_preference、常に最新の
      // AXIS_DEFINITIONS由来）に委ねる方が安全。
      const syncedRoutePreference = axisCatalog.loaded
        ? (syncRoutePreferenceKeys(routePreference, axisCatalog.defaultWeights) ?? routePreference)
        : null;
      // 周回モードでは経由地・目的地の値が残っていても送らない（モード切り替え自体は
      // 値を消さないため、地図上にピンが残っていても周回モード中は無視する。地図表示も
      // routeMode==="destination"のときだけ、page.tsx→MapView.tsx参照）。
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
      // 候補数はステッパー（‹/›）操作のみで変更でき、1〜MAX_ROUTES範囲の整数文字列
      // 以外にはなり得ないため、そのままNumber化して使う。
      const effectiveMaxRoutes = Number(maxRoutesInput);
      const effectiveAssumedSpeed = assumedSpeedKmh;
      const { routes: candidates, conditions, engine, noCandidatesReason } = await generateRoutes({
        latitude: location.latitude,
        longitude: location.longitude,
        distance_km: effectiveDistanceKm,
        distance_tolerance_km: DISTANCE_TOLERANCE_KM,
        route_type: "loop",
        penalty_strength: 1.0,
        // hard_filtersは一般向けルート設定画面（RouteSettingsPanel）が常時操作する対象の
        // ため、weightOverrideEnabledのような上書き専用トグルを介さず常に送る（既定値は
        // backendのDEFAULT_HARD_FILTERSと一致するため挙動は変わらない）。
        hard_filters: hardFilters,
        // RouteGenerateRequest.max_routesは既定値を持つがrequired
        // （distance_tolerance_km/penalty_strengthと同じ扱い）のため、モードに関わらず
        // 常に送る。経由地を伴う目的地ルートはbackendが常に1件へ固定し値を無視する。
        max_routes: effectiveMaxRoutes,
        assumed_speed_kmh: effectiveAssumedSpeed,
        start_time: dynamicLayerTargetTime.toISOString(),
        // レンズが軸を要求していれば、重み0でも区間表示のため風の時変化合成を行う（backend）。
        ...(lens !== LENS_NONE_ID && lens !== LENS_DIFFICULTY_ID ? { lens_axis_id: lens } : {}),
        ...(weightOverrideEnabled && syncedRoutePreference ? { route_preference: syncedRoutePreference } : {}),
        // 目的地モードのときだけ経由地・目的地を送る（backend側の分岐はapi/routers/
        // routes.py参照）。
        ...(routeMode === "destination" && waypoints.length > 0 ? { waypoints } : {}),
        ...(routeMode === "destination" && destination ? { destination } : {}),
      }, setGenerationProgress);
      // backendが目的地をアクセス可能な最寄り地点へ補正した場合、地図上のピンも実際に
      // 使われた地点へ合わせる（そのままだと地図のピン位置と生成されたルートの終点が
      // ずれて見える）。
      if (conditions.corrected_destination) {
        setDestination(conditions.corrected_destination);
      }
      setRoutes(candidates);
      setSelectedRouteId(candidates[0]?.id ?? null);
      // 新しい候補集合に対して、それより前にクリックしていた区間の選択を引き継がない
      // （同じedge_idが新しい生成結果に存在するとは限らず、地図上のマーカーも意味を
      // 失うため）。
      setSelectedRouteSegment(null);
      // 新しい候補が用意できたことを「ルート結果」タブへ知らせる（モバイルのみ表示に
      // 使うが、状態自体はプラットフォーム非依存で立てる）。
      setHasUnseenResults(candidates.length > 0);
      // dirty判定の基準は「いま表示している候補を作った条件」。エラー時は既存候補が
      // 残るため更新しない（tryの成功パスでのみ更新する）
      setGeneratedConditions({
        latitude: location.latitude,
        longitude: location.longitude,
        distanceKm: effectiveDistanceKm,
        maxRoutes: effectiveMaxRoutes,
        assumedSpeedKmh: effectiveAssumedSpeed,
        maxRoutesRelevant: routeMode === "loop" || (routeMode === "destination" && waypoints.length === 0),
        weightsKey: currentWeightsKey,
        routeMode,
        // 補正があった場合は補正後の地点で比較する（地図上のピンも補正後の地点へ
        // 動かしているため、conditionsDirtyが直後に誤ってtrueにならないように揃える）。
        waypointsKey: JSON.stringify({ waypoints, destination: conditions.corrected_destination ?? destination }),
        destinationCorrected: Boolean(conditions.corrected_destination),
      });
      setGeneratedRoutePreference(conditions.route_preference);
      if (candidates.length === 0) {
        // バックエンドが原因を特定できた場合はそれを表示する（routeApi.ts:
        // generateRoutes参照）。特定できない場合のみ汎用文言。
        setErrorMessage(noCandidatesReason ?? "条件に合うルート候補が見つかりませんでした。距離を変えて試してください。");
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
    } finally {
      setLoading(false);
      setGenerationProgress(null);
    }
  }

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
  function renderRouteSectionHeaderActions() {
    return (
      <Button variant="primary" size="sm" type="button" disabled={loading} onClick={routeFormSubmit.handleSubmit}>
        {loading ? (generationProgressLabel ?? "生成中...") : "ルート生成"}
      </Button>
    );
  }

  // 「ルート設定」区分の中身（天候・アプリ名は常設ヘッダにある）。
  // デスクトップの`Disclosure`（summary="ルート設定"）・モバイルの`BottomSheet`
  // （title="ルート設定"）の両方から呼ぶ。見出しはどちらも呼び出し元コンテナが持つため、
  // このセクション自身は見出しを持たない。
  function renderRouteSectionBody() {
    return (
      <>
        {routeFormSubmit.error && <ErrorText>{routeFormSubmit.error}</ErrorText>}
        {errorMessage && <ErrorText>{errorMessage}</ErrorText>}
        <RouteForm
          distance={distanceInput}
          onDistanceChange={setDistanceInput}
          maxRoutes={maxRoutesInput}
          onMaxRoutesChange={setMaxRoutesInput}
          routeMode={routeMode}
          onRouteModeChange={handleRouteModeChange}
          waypointCount={waypoints.length}
          onWaypointsClear={handleWaypointsClear}
          destinationState={destinationState}
          onDestinationButtonClick={handleDestinationButtonClick}
          weightsPanel={renderRouteSettingsSectionBody()}
        />
      </>
    );
  }

  // 一般ユーザー向けルート設定。0次(除外)・軸選択・重みを生成前に調整できる、常時表示の
  // メイン導線（route_preference・weightOverrideEnabledの
  // 状態はpage.tsx冒頭のstate宣言・handleGenerateのコメント参照）。renderRouteSectionBody
  // からのみ呼ばれ、見出しは持たない（呼び出し元コンテナが持つ、上記コメント参照）。
  function renderRouteSettingsSectionBody() {
    return (
      <div className={layerPanelStyles.group}>
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

  // 「ルート結果」見出し脇の右側アクション群（保存・GPX出力・ルートをクリア）。
  // デスクトップ（見出し行）・モバイル（BottomSheetのheaderAction）の両方から同じ中身を
  // 呼ぶ。routes.length===0の間はどちらの呼び出し元も描画自体をスキップする
  // （デスクトップはrenderRouteOutcomeSectionBody自体がnullを返す、モバイルは呼び出し側で
  // routes.lengthを見てheaderActionをundefinedにする）ため、ここでは呼ばれた時点で必ず
  // routes.length>0という前提でよい。
  function renderRouteResultHeaderActions() {
    return (
      <>
        {/* 保存は機能未実装の占位（位置だけ先に確保する）。実装時はdisabledを外す。 */}
        <button type="button" className={styles.outcomeHeaderIcon} disabled title="保存（準備中）" aria-label="保存（準備中）">
          <SaveIcon />
        </button>
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
          <DownloadIcon />
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
          <ClearAllLayersIcon size={14} />
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
  // showHeadingはrenderRouteSettingsSectionBodyと同じ理由（見出しの二重表示回避）で
  // 使い分ける。デスクトップ（既定true）はこのセクション自身の見出し「ルート結果」＋
  // renderRouteResultHeaderActions()（保存・GPX出力・ルートをクリア）をここで描画する。
  // モバイルはBottomSheet自体がtitle="ルート結果"の見出しを持つためshowHeading=falseで
  // 抑制し、同じrenderRouteResultHeaderActions()をBottomSheetのheaderAction propとして
  // 呼び出し側（下のJSX）から渡す。総合難易度の説明はRouteAxisProfile側（総合難易度の
  // 表示の隣）にあり、本ヘッダは操作アイコンのみを持つ。
  function renderRouteOutcomeSectionBody() {
    if (routes.length === 0) return null;

    const showComparisonTab = researchEnabled;
    const outerTabValue = comparisonTabActive ? "comparison" : (selectedRouteId ?? routes[0].id);
    // RouteAxisProfileへは公開軸すべて（axisCatalog.axes）をそのまま渡し、絞り込みは行わない。
    // routeWeightsは重み<=0の軸を「未使用」バッジ付きで表示する判定にのみ使う（生成時点の重み
    // ＝generatedRoutePreference、未生成時のみライブなroutePreferenceへフォールバック）。
    // 全候補で共通のため、候補ごとのTabs.Contentループの外で1回だけ計算する。
    const routeWeights = generatedRoutePreference ?? routePreference;

    return (
      <>
        {conditionsDirty && (
          <p className={styles.dirtyHint}>条件が変更されています。「ルート生成」を押すと反映されます</p>
        )}
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
          value={outerTabValue}
          onValueChange={(value) => {
            // 候補タブ・比較タブいずれへ切り替えても、他候補でクリックしていた区間の
            // 選択は引き継がない（別候補のedge_idを指したまま地図マーカー・内訳が残ると
            // 実態と食い違いを起こすため）。
            setSelectedRouteSegment(null);
            if (value === SAVED_ROUTES_TAB_VALUE) return;
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
                  {/* タブは候補を見分ける最小限の表記（順位番号・距離）だけを持つ。方位・
                      難易度はタブの中身（RouteAxisProfile）に出るためここでは繰り返さない。
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
                  {NON_DIRECTIONAL_ROUTE_IDS.has(route.id)
                    ? route.direction_label
                    : `${index + 1}`}{" "}
                  {route.distance_km.toFixed(1)} km
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
                  overallDifficulty={route.overall_difficulty}
                  difficultyLoad={route.difficulty_load ?? null}
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
              {/* 改善計画T524（T518コードレビューP2指摘の修正）: 以前はライブなroutePreference
                  （「今」の設定）で重み>0の軸のみを表示していたため、あるスロットを風重み0.5で
                  生成→風の重みを0へ変更→別スロットを生成、という手順を踏むと、両スロットの
                  axis_difficultiesに風の値が残っていても比較表から風の行が消えてしまい、
                  「重みを変えて何が変わったか比較する」という比較タブ本来の目的と逆行して
                  いた（ユーザー判断2026-09-01「スロット横断で残す」）。各スロットは生成時点の
                  重み（conditions.route_preference）を保持しているため、いずれかのスロットで
                  一度でも重み>0だった軸は、現在のroutePreferenceの値に関わらず残す。 */}
              <ComparisonPanel
                slots={experimentSlots}
                axisLabels={axisCatalog.axisLabels}
                axes={axisCatalog.axes.filter((axis) =>
                  experimentSlots.some((slot) => (slot.conditions.route_preference[axis.axisId] ?? 0) > 0)
                )}
                materials={materialCatalog}
              />
            </Tabs.Content>
          )}
        </Tabs.Root>
      </>
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
        {/* ユーザー指摘（2026-08-28）「上部バーで、固定部分がなるべく見切れないように」:
            以前は下記.headerActions側だけをposition: sticky; right: 0で常時可視にし、
            この天候の数値側は既定のflex-shrink（1）のまま.weatherHeaderの残り幅に
            押し込まれ、入り切らない分はWeatherPanel自身の内部overflow-x: auto
            （scrollbar-width: noneでスクロールバーの手がかりも無い）へ静かに逃げていた。
            風向・風速はルート評価の起点（ヘッダー本来の主目的、header自身のtitle参照）
            であるため、警報バッジより優先して常に見える側へ入れ替える: flex-shrink: 0で
            常に自然幅を保ち、position: sticky; left: 0で.weatherHeaderの左端に固定する。
            警報バッジ・デバッグアイコン（.headerActions）は代わりに、入り切らなければ
            スクロールしないと見えない状態を許容する。 */}
        <div className={styles.weatherStats}>
          <WeatherPanel amedas={amedas} loading={amedasLoading} error={amedasError} />
          {/* 改善計画T385: 「今日の見通し」（日没・今日の降水確率最大・最大風速・気温
              レンジ）。.weatherStatsと同じ左寄せ固定グループに含め、警報バッジより
              優先して常に見える側に置く（T384調査「常設ヘッダーへ項目を足さず二次
              パネルへ集約する」の結論どおり、瞬間値のWeatherPanelとは別枠のトグルにする）。 */}
          <TodayOutlook weather={weather} loading={weatherLoading} error={weatherError} />
        </div>
        <div className={styles.headerActions}>
          <WarningBadgeList items={warningBadgeItems} />
          {/* 改善計画T519: 研究モードON/OFF・デバッグログ表示アイコン（改善計画T300、
              以前は「開発者」タブ内のボタンだったがそのタブ自体を廃止したためヘッダーへ
              移設していた）を1個のメニューへ集約する（ヘッダーの個別ボタンをこれ以上
              増やさないためのユーザー指示）。debugEnabled時のみデバッグログ項目を表示
              （デバッグモードのON/OFF自体は/adminで切り替える、DebugConsole.tsx参照）。
              DebugConsole自体はposition:fixedのFloatingPanelベースで自己完結しており、
              JSXツリー上のどこに置いても見た目は変わらない。 */}
          <HeaderMenu
            debugEnabled={debugEnabled}
            debugConsoleOpen={debugConsoleOpen}
            onToggleDebugConsole={() => setDebugConsoleOpen((v) => !v)}
          />
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
                {/* サイドバーはモバイルの下部タブと同じ「ルート設定（生成ボタンで反映）／
                    ルート結果（読むだけ）／地図の見え方（即時反映）」の3区分・同じ順序。
                    各区分は独立して開閉し、開閉状態はlocalStorageへ保存する。 */}
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
                  trailing={renderRouteSectionHeaderActions()}
                  open={generateOpen}
                  onOpenChange={setGenerateOpen}
                >
                  {renderRouteSectionBody()}
                </Disclosure>

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
                  {routes.length > 0 ? (
                    renderRouteOutcomeSectionBody()
                  ) : (
                    <p className={styles.emptyHint}>「ルート生成」を押すと候補がここに並びます</p>
                  )}
                </Disclosure>

                {/* 地図の見え方: レイヤーのON/OFF・凡例・絞り込み・色分けの設定はすべてここ。
                    地図の上（MapOverlayControls）にはON/OFFチップと適用中の条件の1行サマリだけを
                    残し、詳細は地図に重ねない（地図の視界を優先）。 */}
                <Disclosure
                  className={styles.blockSection}
                  triggerClassName={styles.blockSummary}
                  bodyClassName={styles.blockBody}
                  id={MAP_SETTINGS_SECTION_TITLE_ID}
                  summary={
                    <>
                      <span aria-hidden="true" className={styles.blockChevron} />
                      地図の見え方
                    </>
                  }
                  open={mapSettingsOpen}
                  onOpenChange={setMapSettingsOpen}
                >
                  {renderMapSettingsSectionBody()}
                </Disclosure>
              </>
            )}
          </aside>
        )}

        {/* app-map-paneはpage.module.css側のモバイル向けMapLibre帰属表示オフセット規則
            （.maplibregl-ctrl-bottom-*、globals.cssのapp-debug-console等と同じマーカークラスの
            手法）が参照するグローバルなマーカークラス。 */}
        <div ref={mapPaneRef} className={`${styles.mapPane} app-map-pane`}>
          <MapView
            routes={routes}
            selectedRouteId={selectedRouteId}
            location={location}
            locationSource={locationSource}
            showElevation={layerVisibility.elevation}
            dynamicWeather={dynamicWeather}
            showRoadType={layerVisibility.roadType}
            showRoadSurface={layerVisibility.roadSurface}
            showDesignation={layerVisibility.designation}
            showTunnel={layerVisibility.tunnel}
            showOneway={layerVisibility.oneway}
            showWindAxis={showWindAxis}
            showGradientAxis={showGradientAxis}
            dedicatedWayValues={dedicatedWayValues}
            dedicatedWayValueDisplays={dedicatedWayValueDisplays}
            dedicatedWayValueLoading={dedicatedWayValueLoading}
            showGradientFill={showGradientFill}
            gradientFillGeojson={gradientFillPayload}
            showStopPoi={layerVisibility.stopPoi}
            showSupplyPoi={layerVisibility.supplyPoi}
            showAccidents={layerVisibility.accidents}
            axisVisibility={axisVisibility}
            secondaryAxisCasingLayerIds={secondaryAxisCasingLayerIds}
            roadHiddenKeysByMode={debouncedRoadHiddenKeysByMode}
            staticLegendHiddenKeysByAxis={debouncedStaticLegendHiddenKeysByAxis}
            routeLayerOn={layerVisibility.route}
            routeStyleModes={routeStyleModes}
            routeStyleModeId={lens}
            hiddenRouteLegendKeys={hiddenRouteLegendKeys}
            onRegionZoomHintChange={setRegionZoomTooWide}
            onViewportChange={handleViewportChange}
            onLayerDataStatusChange={setMapViewLayerDataStatus}
            refreshToken={refreshToken}
            // ユーザー指摘（2026-09-03、「別ルートを選んでいてもずっと常に緑になる」）:
            // T535はexperimentSlots（研究モード中の生成履歴、1件目は常にEXPERIMENT_SLOT_
            // COLORS[0]="#16a34a"=緑）が「ルートをクリア」操作で残る事象のみ対応していたが、
            // タブ切り替え・再生成では引き続き残り続けていた（drawExperimentSlotsは
            // comparisonTabActiveを見ずに無条件で描画するため）。研究モード中の比較用
            // オーバーレイという役割上、実際に「比較」タブを見ているとき以外は地図に
            // 描画する意味が無く、むしろ選択中ルートの色分けと紛らわしいだけだったため、
            // comparisonTabActiveの間だけ渡すよう限定する（スロット自体の記録・
            // ComparisonPanelでの一覧表示は従来どおり researchEnabled のみで動く）。
            experimentSlots={researchEnabled && comparisonTabActive ? experimentSlots : []}
            rampAxes={axisCatalog.rampAxes}
            axisLabels={axisCatalog.axisLabels}
            selectedRouteSegment={selectedRouteSegment}
            onRouteSegmentSelect={setSelectedRouteSegment}
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
            onOriginSet={setManualLocation}
          />

          <LensControl
            lens={lens}
            onLensChange={handleLensChange}
            axisOptions={lensOptions}
            legend={lensLegend}
            hiddenLegendKeys={hasDetail ? hiddenRouteLegendKeys : undefined}
            onToggleLegendKey={hasDetail ? handleRouteLegendToggle : undefined}
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

          {/* 地図下部中央の行。全レイヤー一括OFFボタンを置く（設計原則12: 地図の視界を
              圧迫しない）。 */}
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
              {/* 改善計画T439: conditionsDirty（生成前に条件が変わった）とhasUnseenResults
                  （生成が完了し新しい結果が用意できた）の両方をこのドットで知らせる。
                  前者は生成完了と同時に消える一方後者は生成完了時に立つため、生成の
                  前後を通じて「ルート結果タブを見るべきタイミング」の合図が途切れない。 */}
              {(conditionsDirty || hasUnseenResults) && (
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
            headerAction={renderRouteSectionHeaderActions()}
            heightVh={mobileSheetHeightVh}
            onHeightChange={handleMobileSheetHeightChange}
            onHeightCommit={commitMobileSheetHeight}
          >
            {renderRouteSectionBody()}
          </BottomSheet>

          <BottomSheet
            open={mobileSheet === "routeOutcome"}
            onClose={() => setMobileSheet(null)}
            title="ルート結果"
            titleId={ROUTE_OUTCOME_SHEET_TITLE_ID}
            headerAction={routes.length > 0 ? renderRouteResultHeaderActions() : undefined}
            heightVh={mobileSheetHeightVh}
            onHeightChange={handleMobileSheetHeightChange}
            onHeightCommit={commitMobileSheetHeight}
          >
            {routes.length > 0 ? (
              renderRouteOutcomeSectionBody()
            ) : (
              <p className={styles.emptyHint}>「ルート生成」を押すと候補がここに並びます</p>
            )}
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
