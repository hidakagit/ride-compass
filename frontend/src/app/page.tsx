"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import Disclosure from "@/components/Disclosure/Disclosure";
import { Card } from "@/components/ui/Card/Card";
import MapView from "@/components/Map/MapView";
import MapOverlayControls, { type OverlayLayerChip } from "@/components/MapOverlayControls/MapOverlayControls";
import {
  ClearAllLayersIcon,
  MapAppearanceIcon,
  RouteIcon,
  RouteSettingsIcon,
} from "@/components/Map/icons";
import MapLayersPanel from "@/components/MapLayersPanel/MapLayersPanel";
import BottomSheet, { clampSheetHeightVh, DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import {
  buildMapLayers,
  buildRoadSurfaceSharedLayerIds,
  isAxisStudioLayer,
  mapOverlayExclusiveDomainFor,
  type LayerDataStatusByLayer,
  type MapLayerId,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import { RAMP_AXES, axisMapLayerId, buildAxisRampLegend } from "@/components/Map/axisLayers";
import { gradientAxisLegend } from "@/components/Map/gradientAxisLayer";
import { windAxisLegend } from "@/components/Map/windAxisLayer";
import MapColorLegend, { type MapColorLegendGroup } from "@/components/MapColorLegend/MapColorLegend";
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
  filterRouteStyleModesByPreference,
  getRouteStyleMode,
  isRouteStyleModeId,
  type RouteStyleModeId,
} from "@/components/Map/routeStyleModes";
// 「ルート設定」見出し（renderRouteSectionBody）の見た目に、MapLayersPanel側の既存
// スタイルをそのまま再利用する（CSS Modulesはクラス名の対訳表を返すだけのため、別
// コンポーネントからのimportでも問題なく使える。同じ見た目のUIをここだけのために複製
// しない）。改善計画T518でルート結果パネル側の同種の再利用（旧renderRouteColorSectionBody）
// は撤去済み——現在の唯一の用途は「ルート設定」見出し。
import layerPanelStyles from "@/components/MapLayersPanel/MapLayersPanel.module.css";
import ErrorText from "@/components/ErrorText/ErrorText";
import RouteForm, { type DestinationButtonState, type RouteMode } from "@/components/RouteForm/RouteForm";
import RouteSettingsPanel, {
  DEFAULT_HARD_FILTERS,
  stackBarColorForIndex,
} from "@/components/RouteSettingsPanel/RouteSettingsPanel";
import RouteAxisProfile from "@/components/RouteAxisProfile/RouteAxisProfile";
import AxisContributionBar from "@/components/RouteAxisProfile/AxisContributionBar";
import { FieldLabel } from "@/components/Map/recipeControls";
import WeatherPanel from "@/components/WeatherPanel/WeatherPanel";
import TodayOutlook from "@/components/TodayOutlook/TodayOutlook";
import WarningBadgeList from "@/components/WarningBadge/WarningBadge";
import HeaderMenu from "@/components/HeaderMenu/HeaderMenu";
import DynamicLayerTimeSlider from "@/components/DynamicLayerTimeSlider/DynamicLayerTimeSlider";
import TravelBearingControl from "@/components/TravelBearingControl/TravelBearingControl";
import { PRECIPITATION_INTENSITY_LEVELS } from "@/components/Map/precipitationNowcast";
import { WIND_SPEED_LEGEND_LEVELS, type MapViewport } from "@/components/Map/windLayer";
import { THUNDER_ACTIVITY_LEVELS, TORNADO_POTENTIAL_LEVELS } from "@/components/Map/thunderNowcast";
import { useDynamicWeatherLayers } from "@/hooks/useDynamicWeatherLayers";
import { useDynamicWayValues } from "@/hooks/useDynamicWayValues";
import { gradientGridCellsFromTileResponses } from "@/components/Map/gradientGridFill";
import { useWeatherConditions } from "@/hooks/useWeatherConditions";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { syncRoutePreferenceKeys } from "@/lib/routePreferenceSync";
// 改善計画T548: 従来は/adminへ移設したWeightPanelの既定値定数をここでも使っていたが、
// WeightPanel自体をtotal_score撤去に伴い削除したため@/lib/evaluationAxesへ移設した。
import { DEFAULT_ROUTE_PREFERENCE } from "@/lib/evaluationAxes";
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

// 改善計画T545（旧RouteList.tsxから移設）: 評価軸カタログ（lib/evaluationAxes.ts）から
// 生成する。軸を増やしてもこの文言を直接編集する必要が無い。各軸のdescription（軸スタジオの
// 重みで合成した値であることを説明する文言）を併記し、ルート色分けモードの「総合難易度」
// （区間ごとの絶対基準スコア、routeStyleModes.ts）と同名で紛らわしいという実機指摘に対応する。
// 改善計画T545フォローアップ（ユーザー指摘「おすすめ度の説明とか、ルート結果諸々の補足は
// ルート結果ヘッダのところに情報アイコンをつけて集約できない？」）: 旧
// RouteAxisProfile.tsxの「おすすめ度・総合難易度について」（総合難易度の絶対値としての
// 位置付けを説明する文言）をここへ統合し、候補タブごとに同じ説明を繰り返さず「ルート結果」
// セクション見出し1箇所（renderRouteOutcomeSectionBodyのheader行、モバイルはBottomSheetの
// headerAction）だけに情報アイコンを置く。
const ROUTE_RESULT_HINT = "総合難易度は距離・軸重みを反映した絶対値（各候補の内訳の合計に近い値）です。候補タブはこの値が小さい順に並びます。";

// 改善計画T364/T365（旧RouteList.tsxから移設）: 経由地ルートのid（常に1件、「方位」という
// 概念が無いためタブに順位番号を付けない）。
const NON_DIRECTIONAL_ROUTE_IDS = new Set(["route-waypoints"]);

// 改善計画T551: 目的地ルート（経由地を伴わない起点→目的地のみ）のidは`route-destination-00`
// 形式（via-node方式で複数件になりうる）。経由地ルートと違い「方位」という概念こそ無いが
// 複数件並びうるため、タブラベルには順位番号を付ける（`方向`のような向き語は付けない）。
const DESTINATION_ROUTE_ID_PREFIX = "route-destination";

// 改善計画T550: 区間クリック詳細（selectedRouteSegment）の到達予想時刻表示。旧
// Map/routeSegmentChartPopup.tsのformatTimeLabelと同じフォーマット（撤去済み、
// ボトムシート側へ表示を統合したためこちらへ移設）。
function formatSegmentArrivalTime(iso: string | null): string {
  if (!iso) return "不明";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "不明";
  return date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}

// backend/app/api/routers/routes.py: RouteGenerateRequest.distance_km（Field(gt=0,
// le=MAX_ROUTE_DISTANCE_KM)）と一致させる（目的地モードの自動算出値もこの上限で
// クランプする、handleGenerate参照）。改善計画T471: 以前はここへ「100」を独立に
// ハードコードしていた（RouteForm.tsxにも同じ値の別定義があった）ため、backend側の
// 唯一の情報源（export_openapi.py: ROUTE_GENERATE_CONFIG_PATH）から導出するよう変更した。
const MAX_DISTANCE_KM = routeGenerateConfig.max_distance_km;

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
// 改善計画T524（T518コードレビューP2指摘）: layerVisibility.routeの意味がT518で
// 「色分けレイヤーのみ」から「候補線・ハロー・矢印・色分けレイヤー全体」へ広がったため、
// 過去に明示的にfalseへ変更・保存していた利用者は、更新後にルートを生成しても地図に
// 候補線が1本も出ない状態から始まってしまう（復帰手段の地図チップもhasDetail成立まで
// 無効化されているため気づきにくい）。1回限りの移行マーカー——このキーが無い間だけ
// route:falseをtrueへ強制し、以後はユーザーの選択どおり保存・復元する。
const ROUTE_LAYER_MEANING_MIGRATED_STORAGE_KEY = "ridecompass:route-layer-meaning-migrated-v1";
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
  // 改善計画T405: way_id→wind_penalty配信層（評価軸としての風）。同じ理由で既定OFF。
  windAxis: false,
  // 改善計画T423: 環境グループの勾配gridFill・way_id→勾配配信層。同じ理由で既定OFF。
  gradientFill: false,
  gradientAxis: false,
  // 改善計画T204: 雷ナウキャスト・竜巻発生確度ナウキャスト。同じ理由で既定OFF。
  thunderNowcast: false,
  tornadoNowcast: false,
  // 改善計画T541: 雷放電位置データ。同じ理由で既定OFF。
  liden: false,
  // 改善計画T410でキキクル（危険度分布：土砂・大雨・浸水）+線状降水帯予測マップを
  // 実装した際、当初は既定ON・チップ付きの個別レイヤー（T420）として扱っていたが、
  // 改善計画T432で「防災級の情報は、ユーザー操作を待たず表示すべき（予兆があってから
  // チップをONにするのでは手遅れ）」という当初の動機に立ち返り、キキクル3種は
  // WarningBadgeと同様の常時マウント（チップ無し・layerVisibility自体を持たない）へ
  // 訂正した。線状降水帯予測マップはrisk系統ではなくrasrf系統（降水短時間予報と同じ）と
  // 判明したため「降水」チップの傘下へ統合し、これも個別のlayerVisibilityキーを持たない
  // （frontend/src/hooks/useDynamicWeatherLayers.ts参照）。
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
// 改善計画T432: 線状降水帯予測マップが「降水」チップの傘下（4つ目のソース）へ統合された
// ため、専用の凡例ブロックを`accidents`の「当事者/重大度」と同じ複数ブロックパターンで
// このPRECIPITATION_LEGEND_DETAILS自体へ追加した（実データはriskMap.tsが単一の情報源）。
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
// ユーザー指摘（2026-08-31「矢印の色と背景色が全然違うのは直ってない。凡例に従っていない」）:
// この凡例は矢印（風速そのもの、向きに依存しない）の配色専用で、面塗り（windPenalty、
// 走行方位に対する向かい風/追い風、mapColorLegendGroups参照）とは別の配色系統。以前は
// label=""で無題のまま出しており、「地図の色の凡例」だと誤認しやすかったため、
// 「矢印（風速）」と明示する。
const WIND_LEGEND_DETAILS: LegendFilterSummaryAxis[] = [
  {
    label: "矢印（風速）",
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
// 改善計画T432: キキクル3種（土砂・大雨・浸水）は地図上チップ（▶パネル）自体を持たない
// 常時マウントへ変更したため、専用の凡例ブロック（旧RISK_LEGEND_DETAILS）は表示先を失い
// 撤去した。色の意味（5段階、riskMap.tsが単一の情報源）を確認する導線が無くなった点は
// 既知の制約として残る（改善計画T432以降の課題）。

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
  const { location, locationSource, locationReady, locating, locateError, handleLocateMe, setManualLocation } =
    useLocation();

  // 改善計画T372（実機フィードバック「赤ピンの移動方法が分かりにくい」を受けT366の
  // ボタン武装方式から再設計）: 出発地点は地図上の赤ピン自体をドラッグ&ドロップして
  // 動かす（MapView.tsx: onOriginSet、マーカーのdragendから呼ばれる）。「現在地に戻す」は
  // 既存の「現在地に移動」ボタン（handleLocateMe）がそのまま兼ねるため、専用の
  // ボタン・武装状態はもう持たない。
  // 改善計画T308: 軸カタログ（ramp表示・凡例チップグルーピングを含む）を先頭で取得する。
  // axisVisibility/secondaryAxisCasingLayerIds（下記）・地図チップ組み立てが参照するため、
  // それらより前で宣言する必要がある。取得完了までとエラー時は静的フォールバック
  // （axisLayers.ts: RAMP_AXES等）を返すため、呼び出し側は常に何かしらの一覧を受け取れる。
  const axisCatalog = useAxisCatalog();

  const [routes, setRoutes] = useState<RouteCandidate[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  // 改善計画T550: 地図上でクリックされた区間（MapView.tsx: handleRouteSegmentClickが
  // クリック地点の座標とともに設定するcontrolled state）。non-nullの間、「ルート結果」
  // タブはルート全体の内訳の代わりにこの区間の内訳を表示する（下記
  // renderRouteOutcomeSectionBody参照）。候補タブの切り替え・再生成・ルートクリアの
  // いずれでも古い区間を選択したままにしないよう、該当箇所でnullへ戻す。
  const [selectedRouteSegment, setSelectedRouteSegment] = useState<SelectedRouteSegment | null>(null);
  // 改善計画T545: ルート結果パネルの外側タブを「ルート選択（候補一覧+内訳をひとまとめ）/
  // 比較」の2つから、候補ごとのタブ＋「比較」タブという1段のフラットなタブ列へ再設計した
  // （ユーザー指摘「ルート選択タブは不要、研究タブと同じ形でルートごとタブにして」）。
  // outerタブの選択値はselectedRouteId（候補タブ選択時）とこのフラグ（比較タブ選択時）を
  // 組み合わせて求める——selectedRouteId自体は比較タブを見ている間も「最後に見ていた候補」
  // を保持し続け、地図の色分け対象・selectedCandidate等の既存の使われ方を変えない
  // （比較タブから候補タブへ戻ったとき、見ていた候補がそのまま選択された状態に戻る）。
  const [comparisonTabActive, setComparisonTabActive] = useState(false);
  // 改善計画T439: モバイルで軸調整→再生成した直後、「ルート結果」タブへの視覚的な誘導が
  // 無かった問題への対応（review:ui 2026-08-30 F-5）。conditionsDirtyの通知ドットは
  // 「生成前に条件が変わった」ことを知らせる目的で、生成完了と同時に消える仕様のため、
  // 「新しい結果が用意できた」ことを知らせる別の目的には使えなかった。この状態は
  // 生成成功時にtrue、「ルート結果」タブを開いたらfalseにする（handleGenerate/
  // handleMobileTabClick参照）。
  const [hasUnseenResults, setHasUnseenResults] = useState(false);
  const [loading, setLoading] = useState(false);
  // 改善計画T265: ルート生成のバックグラウンドジョブ化に伴う進捗表示。生成中(loading)の
  // 間だけ意味を持ち、待ち(queued)/実行中(running)の別と経過時間をボタン文言へ反映する
  // （RouteForm.tsx: progressLabel参照）。生成開始直後・完了直後はnull
  // （queued/runningのどちらかが確定するまでの一瞬はloadingのみでラベルを出さない）。
  const [generationProgress, setGenerationProgress] = useState<GenerationProgress | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // 改善計画T364: 地図クリックで指定する経由地（起点→経由地1→...→起点の順で通過する
  // 単一経路を生成する）。指定があれば周回探索は行わない（handleGenerate参照）。
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

  // 改善計画T365-2: 周回（距離指定）/目的地（地図タップで経由地・目的地を
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
  // 改善計画T531: 周回候補の上限件数（backend: RouteGenerateRequest.max_routes、1〜15）。
  // 距離入力と同じくstring stateのまま保持し、送信時にNumber化する。目的地モードでは
  // backendが常に1件へ固定するため無視される（handleGenerate参照）。
  const [maxRoutesInput, setMaxRoutesInput] = useState(String(routeGenerateConfig.default_max_routes));
  // 表示中の候補を生成したときの条件スナップショット。重みは値の組をJSON文字列で比較する
  // （フィールド比較の列挙より差分検知の漏れが出にくい）。
  const [generatedConditions, setGeneratedConditions] = useState<{
    latitude: number;
    longitude: number;
    distanceKm: number;
    maxRoutes: number;
    weightsKey: string;
    // 改善計画T365-2: 目的地モードで生成した場合はdistanceKmが地図上のピンからの
    // 自動算出値になり、distanceInput（RouteFormが表示しない値）とは無関係になるため、
    // conditionsDirtyの距離比較はloopモードで生成したときだけ行う。
    routeMode: RouteMode;
    // 改善計画T468: 目的地モードで生成した経由地・目的地のスナップショット
    // （JSON文字列化して比較、weightsKeyと同じ方式）。以前は保持しておらず、
    // 生成後に経由地を追加・削除・移動してもconditionsDirtyが検知できなかった
    // （routeMode/緯度経度/重みしか比較していなかったため）。
    waypointsKey: string;
  } | null>(null);
  // 改善計画T440: 表示中のルートを実際に生成した瞬間のroute_preference（重み）。
  // routePreference自体はルート設定パネルが常時編集するライブなstateのため、生成後に
  // 再生成せず重みだけ変更すると、表示中のルートが実際に評価された時の重みと
  // 「生成したルートの色分け」メニューがズレる（ユーザー指摘）。バックエンドは
  // 生成に実際に適用したroute_preferenceを`conditions.route_preference`として既に
  // エコーバックしている（`GenerationConditions`、backend/app/api/routers/routes.py）ため、
  // 生成成功時にここへ複製するだけでよい（バックエンド変更不要）。
  const [generatedRoutePreference, setGeneratedRoutePreference] = useState<RoutePreferenceWeights | null>(null);

  // 評価重みのリクエスト上書き（研究インターフェース改善 §10-1/4）。overrideEnabled=falseの間は
  // 生成リクエストからroute_preferenceを省略し、既存挙動（既定値）を完全に維持する
  // （一般ユーザーには影響しない）。route_preference/routePreference自体は改善計画T267で
  // 一般向けルート設定画面（RouteSettingsPanel）とも共有する状態になった（withAutoEnableに
  // より、どちらのパネルを操作してもこのフラグが自動でONになる）。
  const [weightOverrideEnabled, setWeightOverrideEnabled] = useStoredJsonState(
    "ridecompass:weight-override-enabled",
    false
  );
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

  // 改善計画T365: 生成済みのルート結果（候補一覧・地図描画・選択状態）だけをリセットする。
  // 経由地・目的地のピンは対象外（別々の「クリア」操作として使い分けられるようにする）。
  // 改善計画T535（ユーザー報告「ルートをクリアしても地図に緑の線が残る」の調査で発見）:
  // 研究モード中の生成はexperimentSlotsへも記録され地図へ重ね描きされる
  // （EXPERIMENT_SLOT_COLORS[0]="#16a34a"=緑）が、以前はこの関数がexperimentSlotsに
  // 触れておらず、リポジトリ全体を見てもexperimentSlotsを空にする経路が他に一切
  // 無かった（ページ再読み込み以外に消す手段が無い状態）。「ルートをクリア」を押した
  // 見た目どおり地図が空になるよう、実験スロットも同時にクリアする（ユーザー判断
  // 2026-09-02: 比較履歴を残す設計よりも「クリアしたら地図が本当に空になる」という
  // 一般的な期待を優先）。
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
        // 改善計画T524（T518コードレビューP2指摘）: 1回限りの移行。マーカーが未設定の間だけ
        // route:falseをtrueへ戻す（T518以前の意味[色分けレイヤーのみ非表示]で保存された
        // 値を、新しい意味[全レイヤー非表示]のまま引き継がせないため）。マーカー自体は
        // route値に関わらず必ず立て、次回以降はユーザーの選択どおり尊重する。
        try {
          if (window.localStorage.getItem(ROUTE_LAYER_MEANING_MIGRATED_STORAGE_KEY) == null) {
            if (next.route === false) {
              next.route = true;
              // 実バグ修正（2026-09-03ユーザー指摘「進行方向の矢印が以前は出てたのに消えている」）:
              // useStoredStateの復元effect（useStoredState.ts）はsetValueのみを呼びcommit
              // （localStorageへの書き戻し）は行わない。この移行はreloadKey（axisCatalog.loaded）
              // 経由でマウント直後（false）→フェッチ完了後（true）の2回deserializeが走るが、
              // 書き戻さないと1回目でnext.route=trueへ補正してもlocalStorage上は元のroute:false
              // のまま残り、2回目のdeserializeが同じ生値を読み直して補正前のfalseへ静かに
              // 巻き戻っていた（マーカー自体は1回目で立つため2回目は移行ブロックに入らずfalseの
              // まま確定していた）。route:falseが復元されるとMapView側のapplyRouteLayerVisibility
              // （候補線・ハロー・矢印・区間色分けの4レイヤーをまとめて出し分ける）が全て非表示に
              // なり、「以前は出ていた矢印が消えている」という報告と一致する。
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
    { serialize: (v) => v, deserialize: (raw) => (isRouteStyleModeId(axisCatalog.routeStyleModes, raw) ? raw : null) },
  );
  // 改善計画T434/T440: 「評価で有効にした軸」（route_preferenceの重み>0）だけを選択肢として
  // 動的に見せる。判定には生成済みルートを実際に評価した瞬間の重み
  // （generatedRoutePreference、上記）を使う——ライブなroutePreferenceをそのまま使うと、
  // 生成後に重みだけ変更（再生成せず）した場合に表示中のルートの実際の評価内容と
  // メニューがズレる（T440、ユーザー指摘）。ルート未生成（null）の間はライブな
  // routePreferenceをプレビュー用フォールバックとして使う。ユーザー指摘（2026-09-03）:
  // 一度この重みフィルタを撤去したが、意図は逆（重み0の軸は選択肢からも消してほしい）と
  // 確認できたため復元した。
  const filteredRouteStyleModes = useMemo(
    () => filterRouteStyleModesByPreference(axisCatalog.routeStyleModes, generatedRoutePreference ?? routePreference),
    [axisCatalog.routeStyleModes, generatedRoutePreference, routePreference],
  );
  useEffect(() => {
    if (filteredRouteStyleModes.some((mode) => mode.id === routeStyleModeId)) return;
    // 改善計画T524（T518コードレビューP3指摘）: RouteStyleModeIdは事実上string
    // （routeStyleModes.ts参照）のため、対応する地図色分けモードが無いidを
    // setRouteStyleModeIdへ渡してもコンパイルエラーにならず、この巻き戻しが黙って
    // 発生していた（T518実機確認で発覚した「非対応軸チップが無反応に見えるバグ」の
    // 根本原因）。原因調査ができるよう、「idが評価軸としては実在するが地図色分けに
    // 対応していない」場合と「idが評価軸としても実在しない」場合を区別して警告ログを
    // 残す（getRouteStyleMode: routeStyleModes.tsの既存パターンを踏襲）。
    const matchesKnownAxis = axisCatalog.axes.some((axis) => axis.axisId === routeStyleModeId);
    debugLog(
      "map:route-style-mode",
      matchesKnownAxis
        ? `route style mode "${routeStyleModeId}" is a known axis but has no map-coloring mode ` +
          `(weight=0), falling back to "${filteredRouteStyleModes[0].id}"`
        : `route style mode "${routeStyleModeId}" is not a known axis id, falling back to ` +
          `"${filteredRouteStyleModes[0].id}"`,
      { requestedId: routeStyleModeId, availableIds: filteredRouteStyleModes.map((mode) => mode.id) },
      "warn"
    );
    setRouteStyleModeId(filteredRouteStyleModes[0].id);
  }, [filteredRouteStyleModes, routeStyleModeId, setRouteStyleModeId, axisCatalog.axes]);
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
    (key: string) => toggleHiddenLegendKey(routeStyleModeId, key),
    [routeStyleModeId, toggleHiddenLegendKey],
  );
  // 改善計画T518: RouteAxisProfileの軸チップの色ドットを、RouteSettingsPanelの凡例チップ
  // と同じ色にする（同じ軸なら両パネルで同じ色、という視覚的な一貫性のため）。
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

  // 改善計画T308: MAP_LAYERS（静的フォールバック）ではなく、axisCatalog.rampAxes
  // （実行時フェッチ、軸スタジオの公開軸を含む）から組み立てたレイヤーカタログを使う。
  // 改善計画T406: handleLayerToggle（直下）が排他ドメイン判定のためmapLayers全体を
  // 参照する必要があり、以前はoverlayLayers組み立て（後方）の直前で定義していたものを
  // ここへ前倒しした（依存するaxisCatalogは既にこの手前[275行目付近]で定義済み）。
  const mapLayers = useMemo(() => buildMapLayers(axisCatalog.rampAxes), [axisCatalog.rampAxes]);
  const roadSurfaceSharedLayerIds = useMemo(
    () => buildRoadSurfaceSharedLayerIds(axisCatalog.rampAxes),
    [axisCatalog.rampAxes]
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
  //
  // 改善計画T406: パネル構成再編（道路/環境/スポットの3チップ・3排他ドメイン、
  // docs/tasks/T400.md「1. パネルの最上位グルーピング」節）に伴い、チップ本体のON/OFFを
  // 「同一排他ドメイン内は1つだけ選べる」ラジオボタン方式へ変更する。「環境」（面）・
  // 「スポット」（点）はそれぞれ独立した排他ドメインを持ち、「道路」（線）はT406時点は
  // 「評価軸」と排他ドメインを共有していたが、T418で評価軸チップ自体を地図UIから撤去した
  // ため単独ドメインになった（mapLayers.ts: mapOverlayExclusiveDomainFor参照）。
  // ONにする操作のときだけ、同じ排他ドメインに属する他の全レイヤーIDをOFFにする
  // （OFFにする操作自体は他レイヤーに影響しない）。ルート等どの排他ドメインにも属さない
  // レイヤーは対象外のまま複数同時ONを許す（従来どおり）。
  //
  // 改善計画T418: 軸スタジオ由来のレイヤー（isAxisStudioLayer、ramp軸・windAxis）は
  // 地図上チップとしては撤去しルート設定パネルへ移設したが、複数を同時にONにすると
  // 同じ道路ジオメトリへ線を重ねて見にくくなるという排他ドメインの元々の目的
  // （道路と評価軸を1つの"line"ドメインで束ねていた理由）はそのまま当てはまるため、
  // 地図上チップの3ドメイン（road/environment/spot）とは独立に、軸スタジオ由来の
  // レイヤー同士だけで1つだけ選べる排他制御を維持する。
  const handleLayerToggle = useCallback(
    (id: MapLayerId, on: boolean) => {
      setLayerVisibility((prev) => {
        const next: MapLayerVisibility = { ...prev, [id]: on };
        if (on) {
          const layer = mapLayers.find((l) => l.id === id);
          const domain = layer ? mapOverlayExclusiveDomainFor(layer) : undefined;
          if (domain) {
            for (const other of mapLayers) {
              if (other.id === id) continue;
              if (mapOverlayExclusiveDomainFor(other) === domain) {
                next[other.id] = false;
              }
            }
          } else if (layer && isAxisStudioLayer(layer)) {
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

  // 改善計画T518: 以前はrenderRouteColorSectionBody内のローカル関数だったが、
  // RouteAxisProfile（「ルート選択」タブへ統合済み）から直接propsとして渡すため
  // page.tsxのトップレベルへ引き上げた。ルートの色分けモードを選ぶと、地図上の
  // 「ルート」チップ（layerVisibility.route）がOFFなら自動でONにする（選んだのに
  // 見えないままだと気づきにくいための配慮、以前からの挙動を維持）。
  const handleRouteModeSelect = useCallback(
    (id: RouteStyleModeId) => {
      setRouteStyleModeId(id);
      if (!layerVisibility.route) handleLayerToggle("route", true);
    },
    [layerVisibility.route, handleLayerToggle, setRouteStyleModeId],
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
    ? `色分け: ${getRouteStyleMode(filteredRouteStyleModes, routeStyleModeId).label}${hiddenRouteLegendKeys.length > 0 ? "・一部非表示" : ""}`
    : null;
  const routeLegendDetails = useMemo<LegendFilterSummaryAxis[]>(
    () =>
      hasDetail
        ? [
            {
              label: "",
              legend: getRouteStyleMode(filteredRouteStyleModes, routeStyleModeId).legend,
              hiddenKeys: hiddenRouteLegendKeys,
            },
          ]
        : [],
    [hasDetail, routeStyleModeId, hiddenRouteLegendKeys, filteredRouteStyleModes],
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

  // 地図上のチップ行はレイヤーカタログ（mapLayers）から組み立てる。レイヤーを追加したら
  // summaryの対応をここへ1行足すだけでよい（チップ・凡例パネルの描画は汎用）。
  const overlayLayers = useMemo<OverlayLayerChip[]>(() => {
    // 改善計画T468: summary/legendDetailsの組み立てが、5〜8段ネストした三項演算子
    // チェーンでlayer.idを1つずつ比較していたのを、layer.id→値のルックアップへ置き換えた
    // （可読性向上、フォールバック[staticFilterSummaries]は従来どおり最後に見る）。
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
      thunderNowcast: THUNDER_LEGEND_DETAILS,
      tornadoNowcast: TORNADO_LEGEND_DETAILS,
    };
    return mapLayers.map((layer) => {
        // 改善計画T418: windAxis（way_id→wind_penalty配信層）・ramp軸（axis:${string}）は
        // isAxisStudioLayerによりMapOverlayControls自体がチップとして描画しない
        // （評価軸はルート設定パネルへ移設済み、mapLayers.ts参照）ため、このoverlayLayers
        // 配列に含めるのは「全レイヤー一括OFF」ボタン（handleClearAllLayers、下記）が
        // layerVisibilityへ引き続きアクセスできるようにするためだけの目的になった。
        // ルート確定後の風の一律色分け終了（旧T414時点のdisabled分岐）はRouteSettingsPanel.tsx:
        // renderMapColorToggleのhasDetail判定へ移設済み。
        // disabledとtitleが別々に同じlayer.id判定を繰り返さないよう、理由の文言と紐付けて
        // 1箇所で決める（T414時点の設計を踏襲、無効化理由が増えても1本追加するだけで
        // disabled/titleの両方に反映される）。
        // 改善計画T524（T518コードレビューP2指摘）: 以前はhasDetail（segments取得済み）を
        // 見ていたが、RouteAxisProfileの表示条件（selectedCandidateのみ）とズレていた
        // ——候補選択直後・segments未取得の間、地図の「ルート」チップは無効化されたままな
        // のに、同時に表示されるRouteAxisProfileのチップ操作でlayerVisibility.routeがON
        // に変わってしまい、地図チップから直接OFFへ戻せない状態が生じていた。両者を
        // selectedCandidate基準へ揃える。
        const disabledReason = layer.id === "route" && !selectedCandidate ? "ルートを生成・選択すると使えます" : null;
        const disabled = disabledReason !== null;
        const summary = layer.id in summaryByLayerId
          ? (summaryByLayerId[layer.id] ?? null)
          : (staticFilterSummaries[layer.id]?.summary ?? null);
        const legendDetails =
          legendDetailsByLayerId[layer.id] ?? staticFilterSummaries[layer.id]?.legendDetails;
        // ユーザー判断（2026-08-25）: 動的グループ（降水ナウキャスト・風・雷・竜巻）は
        // 絞り込み機能を持たないため「地図の見え方」パネルの行自体を撤去した
        // （MapLayersPanel.tsx参照）。地図上チップの▶パネル本体へ説明文を常時表示する
        // 対応は「読みにくい」というフィードバックを受けて取りやめた（凡例のみを表示する）。
        // 改善計画T334: 上記とは別に、折りたたみ中の「表示する項目を選ぶ」設定パネル
        // （MapOverlayControls.tsx: renderVisibilitySettings）側は、各メンバー行に個別の
        // 情報アイコンを置き、押したメンバーだけ説明文を表示する形で復活させた
        // （panelHintは推定/観測/動的の全メンバーへ渡す。同時に常時表示にはしないため
        // 上記のT317同日追記の判断とは矛盾しない）。
        // 改善計画T468: 以前はlayer.idのハードコード列挙で「動的グループ」を再判定しており、
        // mapLayers.ts側の単一ソースdataNature==="dynamic"（本来の判定基準）とズレていた
        // （windAxis/gradientAxis[isAxisStudioLayerで別途チップ非表示のため実害無し]に加え、
        // gradientFillが列挙漏れで「[設定はサイドバー]」を誤って付与されていた——gradientFillは
        // 環境グループの実チップとして表示されるため実害あり）。dataNature自体を見る形へ
        // 修正し、今後dataNature="dynamic"の新規レイヤーが増えても追従する。
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
          // 地図上チップのカテゴリ束ね（改善計画T128、MapOverlayControls.tsx）用。
          category: layer.category,
          dataNature: layer.dataNature,
          // 改善計画T334: 「表示する項目を選ぶ」設定パネルの個別情報アイコン用の説明文。
          panelHint: layer.panelHint,
        };
      });
  }, [
    selectedCandidate,
    layerVisibility,
    roadSurfaceLegendDetails,
    roadSurfaceSummary,
    roadTypeLegendDetails,
    roadTypeSummary,
    routeLegendDetails,
    routeSummary,
    staticFilterSummaries,
    mapLayers,
  ]);

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
    // 改善計画T439: 「ルート結果」タブを開いたら、新着結果の合図は役目を終える。
    if (sheet === "routeOutcome") setHasUnseenResults(false);
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

  // 今日の見通し（TodayOutlook向け、Open-Meteo予報）・最寄りアメダス実測値（WeatherPanel＝
  // 常設ヘッダー向け）・警告バッジ3種（JMA警報・注意報T205／WBGT T174／河川氾濫予報T212）の
  // フェッチ・状態管理（改善計画T375でuseWeatherConditionsへ抽出、T387フォローアップで
  // weather[Open-Meteo]とamedas[アメダス実測]を独立フェッチへ分離）。
  // locationReadyになるまで待ち、その後はlocationが変わるたびに再フェッチする。
  const {
    weather,
    weatherLoading,
    weatherError,
    amedas,
    amedasLoading,
    amedasError,
    warningBadgeItems,
  } = useWeatherConditions(location, locationReady);

  // 動的気象レイヤー（降水ナウキャスト・風/延長降水予報・雷/竜巻ナウキャスト・キキクル）の
  // フェッチ・共有タイムライン・MapView向け描画ペイロード（改善計画T375でuseDynamicWeather
  // Layersへ抽出）。各要素は対応するshow*がtrueの間だけフェッチする（キキクル3種は
  // 改善計画T432で「防災」カテゴリとして常時マウントへ変更したためshow*を持たない）。
  const showPrecipitationNowcast = layerVisibility.precipitationNowcast;
  const showThunderNowcast = layerVisibility.thunderNowcast;
  const showTornadoNowcast = layerVisibility.tornadoNowcast;
  const showLiden = layerVisibility.liden;
  const showWindVector = layerVisibility.windVector;
  // 環境グループの風penalty gridFill（改善計画T414）。windVectorのチップON/OFFとは独立に
  // ルート確定後（hasDetail）はfalseへ倒す（T414契約: ルート確定後はルート自身の実際の
  // 進行方向・到達時刻を使うrouteStyleModes「風」モードへ委ねる）。useDynamicWeatherLayers
  // 呼び出しより前に計算する必要がある（改善計画T432でオプションとして渡すため）。
  const showWindPenaltyFill = showWindVector && !hasDetail;
  // ユーザー要望（2026-08-31、「今は軸毎やレイヤ毎に走行方位が決められるけれど、1つでいい」）:
  // 動的材料の状態別表現契約（docs/tasks/T400.md「2.」節）の[時刻,向き]のうち「向き」を、
  // 風・勾配それぞれ独立したstate（旧windBearingDeg/gradientBearingDeg）から、実際の
  // 進行方向という単一の概念を表す1つの共有state（travelBearingDeg）へ統合した。
  // 「環境」グループ（風penalty gridFill・勾配gridFill）・評価軸としての風/勾配
  // （windAxis/gradientAxis）のいずれもこの1つの値を共有する。設定UIは地図上の
  // TravelBearingControl（`components/TravelBearingControl/`）1箇所へ集約し、
  // RouteSettingsPanel内の「走行方位を設定」ボタン・地図下部の個別コンパス
  // （bottomControlRow）は撤去した。
  const [travelBearingDeg, setTravelBearingDeg] = useState(0);
  const {
    dynamicWeather,
    sliderFrames,
    sliderIndex,
    sliderCurrentIndex,
    handleSliderIndexChange,
    handleDynamicLayerNow,
    dynamicLayerLoading,
    dynamicLayerError,
    dynamicLayerTargetTime,
  } = useDynamicWeatherLayers({
    showWindVector,
    windBearingDeg: travelBearingDeg,
    showWindPenaltyFill,
    showPrecipitationNowcast,
    showThunderNowcast,
    showTornadoNowcast,
    showLiden,
    mapViewport,
  });

  // way_id→wind_penalty配信層（改善計画T405→T414で作り直し、T418でルート設定パネルへ
  // 移設）。評価軸としての風——上のuseDynamicWeatherLayers（「環境」グループの面・矢印表示）
  // とは独立したフェッチだが、
  // [時刻,向き]の入力（dynamicLayerTargetTime・windBearingDeg）は共有する。mapViewportは
  // 同じMapView.tsx: onViewportChange経由の値を共有する。
  //
  // ルート確定後（hasDetail）は、視界内の全道路への一律色分けというこの機能の役割自体を
  // 終了する（T414契約: ルート確定後はルート自身の実際の進行方向・到達時刻を使う
  // routeStyleModes「風」モードへ委ねる。改善計画T418で起動元が地図上チップから
  // ルート設定パネルへ移ったため、hasDetail時のdisabled化は
  // `RouteSettingsPanel.tsx: renderMapColorToggle`が担う）。
  const showWindAxis = layerVisibility.windAxis && !hasDetail;
  const windAxisData = useDynamicWayValues("wind", showWindAxis, mapViewport, travelBearingDeg, dynamicLayerTargetTime);

  // way_id→勾配（effective_gradient）配信層（改善計画T423）。windAxisと同型だが、勾配は
  // 時刻に依存しないため（docs/tasks/T400.md「2.」節）dynamicLayerTargetTimeを共有しない。
  // 向き（travelBearingDeg）は風と共有する（上記の統合コメント参照）。「環境」グループ
  // （gradientFill、gridFill面表示）・評価軸としての勾配（gradientAxis）が同じ1つの入力
  // （向き）を共有する（T400.md「2.」節と同じ構造）。表示のON/OFF自体は別チップのまま。
  const showGradientFill = layerVisibility.gradientFill && !hasDetail;
  const showGradientAxis = layerVisibility.gradientAxis && !hasDetail;
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
  // 改善計画T483: dedicatedWayValueBoundaries（改善計画T473）と同じ理由
  // （design-principles.md構造仕様3: 軸ごとにpropを新設しない）で、以前は
  // windAxisPenalties/gradientAxisValuesという軸ごとに別名のpropだったものを
  // axisId→(way_id→値)の汎用Mapへ統合した。useDynamicWayValues自体は
  // materialIdごとに個別インスタンス化する設計（デバウンス・レース対策がaxis間で
  // 独立している必要があるため、hooks/useDynamicWayValues.ts参照）のままで変更していない
  // ——統合するのはMapViewへ渡す直前のprop形状だけ。
  const dedicatedWayValues = useMemo(
    () =>
      new Map<string, ReadonlyMap<number, number>>([
        ["wind", windAxisData.values],
        ["gradient", gradientAxisData.values],
      ]),
    [windAxisData.values, gradientAxisData.values]
  );
  // 改善計画T473: `dedicated_way_value_layer`軸（wind/gradient）の軸スタジオ
  // display_thresholds_overrideをMapViewへ配線する。以前はgradientBoundaries（T443）・
  // windBoundaries（T466）という軸ごとに別名のuseMemo・propだったが、design-principles.md
  // 構造仕様3（軸ごとにpropを新設しない）に違反していたため、axisCatalog.axesから
  // dedicatedWayValueLayer===trueの軸を横断的に抽出し、axisId→しきい値配列の汎用Mapへ
  // 統合した（3件目の動的材料が増えてもこのuseMemo自体の変更は不要）。gradientの
  // dedicatedWayValueLayerフラグはaxisCatalog.axes側（GET /api/axis-catalog由来）で
  // 正しくtrueになる（evaluationAxes.tsのビルド時静的フォールバックが誤ってfalse固定
  // していた問題もあわせて修正済み、evaluationAxes.ts参照）。
  const dedicatedWayValueBoundaries = useMemo(() => {
    const map = new Map<string, readonly number[]>();
    for (const axis of axisCatalog.axes) {
      if (axis.dedicatedWayValueLayer && axis.displayThresholdsOverride) {
        map.set(axis.axisId, axis.displayThresholdsOverride);
      }
    }
    return map;
  }, [axisCatalog.axes]);
  // 改善計画T513: dedicatedWayValueBoundariesと対になる、段階ごとの体感ラベルの汎用Map。
  // 色分けのしきい値自体（MapViewへ渡す配色式用）には影響しないため、MapViewProps側は
  // 変更せずMapColorLegend向けのmapColorLegendGroups組み立てだけで使う。
  const dedicatedWayValueBandLabels = useMemo(() => {
    const map = new Map<string, readonly string[]>();
    for (const axis of axisCatalog.axes) {
      if (axis.dedicatedWayValueLayer && axis.displayBandLabelsOverride) {
        map.set(axis.axisId, axis.displayBandLabelsOverride);
      }
    }
    return map;
  }, [axisCatalog.axes]);

  // ユーザー要望（2026-08-31、「地図上の色付の凡例が欲しい。例えば、勾配ONにした時に
  // 青くなる道路は何なのか、その度合いが分かればいい」）: 「地図で色分け」がONの軸ぶんだけ、
  // 地図左下に色→値の凡例を出す（MapColorLegend参照）。ramp軸（axisVisibility）・
  // windAxis/gradientAxis（showWindAxis/showGradientAxis、専用way_id配信層）の3系統を
  // 横断して集める——RouteSettingsPanel.tsx: mapColorLayerIdForが軸id→レイヤーIDを
  // 解決するのと同じ2分岐（secondaryAxes由来のramp／dedicatedWayValueLayer）だが、
  // ここでは「今ONになっているものの凡例」を集めるのが目的のため判定の向きが逆
  // （レイヤーID→軸ではなく、既知の3系統それぞれについてON状態を直接見る）。
  const mapColorLegendGroups = useMemo<MapColorLegendGroup[]>(() => {
    const groups: MapColorLegendGroup[] = [];
    for (const axis of axisCatalog.rampAxes) {
      if (axisVisibility[axisMapLayerId(axis.axisId)]) {
        groups.push({
          axisId: axis.axisId,
          label: axis.label,
          bands: buildAxisRampLegend(axis).map((entry) => ({ label: entry.label, color: entry.color })),
        });
      }
    }
    // ユーザー指摘（2026-08-31「矢印の色と背景色が全然違うのは直ってない。凡例に従って
    // いない」）: 評価軸（線、showWindAxis/showGradientAxis）だけでなく環境グループの
    // gridFill（showWindPenaltyFill/showGradientFill、MapOverlayControlsの「環境」チップ
    // から一番先に触る導線）も同じ配色・しきい値（windPenaltyFillColorExpression/
    // windAxisLegendが共有する契約、windPenalty.ts冒頭コメント参照）を使うため、この凡例で
    // 説明できる。以前はshowWindAxis/showGradientAxis（RouteSettingsPanel側の「地図で色分け」
    // トグル）単独でしか出しておらず、「環境」チップだけをONにした状態（矢印+面塗り）では
    // 面塗りの色を説明する凡例がどこにも出ない穴になっていた（矢印自体は風速ベースの別配色
    // [WIND_SPEED_LEGEND_LEVELS]の専用ポップオーバーを持つため、それを「背景色の凡例」と
    // 誤認しやすかった）。
    if (showWindAxis || showWindPenaltyFill) {
      groups.push({
        axisId: "wind",
        label: axisCatalog.axisLabels.wind ?? "風",
        bands: windAxisLegend(dedicatedWayValueBoundaries.get("wind"), dedicatedWayValueBandLabels.get("wind")),
      });
    }
    if (showGradientAxis || showGradientFill) {
      groups.push({
        axisId: "gradient",
        label: axisCatalog.axisLabels.gradient ?? "勾配",
        bands: gradientAxisLegend(
          dedicatedWayValueBoundaries.get("gradient"),
          dedicatedWayValueBandLabels.get("gradient")
        ),
      });
    }
    return groups;
  }, [
    axisCatalog.rampAxes,
    axisCatalog.axisLabels,
    axisVisibility,
    showWindAxis,
    showWindPenaltyFill,
    showGradientAxis,
    showGradientFill,
    dedicatedWayValueBoundaries,
    dedicatedWayValueBandLabels,
  ]);

  // 生成条件のうち重み設定の比較キー（上書き無効時はnull＝バックエンド既定値を表す）。
  // 改善計画T292: 車ストレス専用レシピ（旧car_stress_recipe等）は専用Pythonレシピの
  // 廃止に伴い比較対象から削除した。
  const currentWeightsKey = JSON.stringify({
    weights: weightOverrideEnabled ? { routePreference } : null,
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
      // 改善計画T531: 候補件数も距離と同じ理由（loopモードでのみ意味を持つ生成条件）で
      // dirty判定へ組み込む。目的地モードはbackendが件数を無視するため比較しない。
      (generatedConditions.routeMode === "loop" && Number(maxRoutesInput) !== generatedConditions.maxRoutes) ||
      (generatedConditions.routeMode === "destination" &&
        JSON.stringify({ waypoints, destination }) !== generatedConditions.waypointsKey) ||
      currentWeightsKey !== generatedConditions.weightsKey);

  async function handleGenerate(distanceKm: number) {
    setLoading(true);
    setGenerationProgress(null);
    setErrorMessage(null);
    try {
      // 改善計画T303: 送信直前にキー整合を補正する（上のコメント参照）。RouteSettingsPanel
      // がマウント済みならこの時点で既にキーは一致しており synced は null になる。
      // 改善計画T320: axisCatalog.defaultWeights自体がまだ軸スタジオの現在状態を反映して
      // いない（axisCatalog.loaded===false、未取得・取得失敗）場合、この同期は静的フォール
      // バック（既存7軸）に合わせてroutePreferenceを書き換えてしまい、実際の公開軸集合とは
      // 無関係な値になる。この場合はroute_preference自体を省略し、backend側の既定値
      // （load_route_preference、常に最新のAXIS_DEFINITIONS由来）に委ねる方が安全。
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
      // 改善計画T531/T557: 周回候補の上限件数。RouteForm側の候補数入力欄は目的地モードでは
      // 非表示になり検証もされないため、maxRoutesInputが空文字・範囲外のまま残っていても
      // 送信前にここで検証する（destinationモードはbackendが常に1件へ固定し値自体を無視する
      // ため、この検証漏れは主に周回モードへ戻したときの再送信を守るためのもの）。
      const parsedMaxRoutes = Number(maxRoutesInput);
      const effectiveMaxRoutes =
        Number.isInteger(parsedMaxRoutes) && parsedMaxRoutes >= 1 && parsedMaxRoutes <= routeGenerateConfig.max_routes
          ? parsedMaxRoutes
          : routeGenerateConfig.default_max_routes;
      const { routes: candidates, conditions, engine, noCandidatesReason } = await generateRoutes({
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
        // 改善計画T531: 周回候補の上限件数。RouteGenerateRequest.max_routesは既定値を
        // 持つがrequired（distance_tolerance_km/penalty_strengthと同じ扱い）のため、
        // モードに関わらず常に送る。経由地・目的地指定ルートはbackendが常に1件へ
        // 固定し無視する。
        max_routes: effectiveMaxRoutes,
        ...(weightOverrideEnabled && syncedRoutePreference ? { route_preference: syncedRoutePreference } : {}),
        // 改善計画T364/T365-2: 目的地モードのときだけ経由地・目的地を送る
        // （backend側の分岐はapi/routers/routes.py参照）。
        ...(routeMode === "destination" && waypoints.length > 0 ? { waypoints } : {}),
        ...(routeMode === "destination" && destination ? { destination } : {}),
      }, setGenerationProgress);
      setRoutes(candidates);
      setSelectedRouteId(candidates[0]?.id ?? null);
      // 改善計画T550: 新しい候補集合に対して、それより前にクリックしていた区間の選択を
      // 引き継がない（同じedge_idが新しい生成結果に存在するとは限らず、地図上のマーカーも
      // 意味を失うため）。
      setSelectedRouteSegment(null);
      // 改善計画T439: 新しい候補が用意できたことを「ルート結果」タブへ知らせる
      // （モバイルのみ表示に使うが、状態自体はプラットフォーム非依存で立てる）。
      setHasUnseenResults(candidates.length > 0);
      // dirty判定の基準は「いま表示している候補を作った条件」。エラー時は既存候補が
      // 残るため更新しない（tryの成功パスでのみ更新する）
      setGeneratedConditions({
        latitude: location.latitude,
        longitude: location.longitude,
        distanceKm: effectiveDistanceKm,
        // 改善計画T531: 目的地モードではbackendが無視する値のため意味を持たないが、
        // conditionsDirtyの比較はroute_mode==="loop"のときだけこの値を見る（上記参照）。
        maxRoutes: effectiveMaxRoutes,
        weightsKey: currentWeightsKey,
        routeMode,
        waypointsKey: JSON.stringify({ waypoints, destination }),
      });
      setGeneratedRoutePreference(conditions.route_preference);
      if (candidates.length === 0) {
        // 改善計画T441: バックエンドが原因を特定できた場合はそれを表示する
        // （routeApi.ts: generateRoutes参照）。特定できない場合のみ従来の汎用文言。
        setErrorMessage(noCandidatesReason ?? "条件に合うルート候補が見つかりませんでした。距離を変えて試してください。");
      } else if (researchEnabled) {
        // 実験スロットへの記録は研究モード中の生成のみ（研究用機能を一般ユーザーの
        // 通常操作から隠す方針、§14。ログ表示のデバッグモードとは独立、改善計画T29）。
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
      // ここでも記録する（2026-08-24実機調査「fail to fetchがどこにもログされない」を受けて
      // 監査、多層防御として残す）。
      debugLog("api:route", "ルート生成ハンドラで例外", { error: message }, "error");
      setErrorMessage(message);
    } finally {
      setLoading(false);
      setGenerationProgress(null);
    }
  }

  // 改善計画T265: RouteForm（デスクトップ・モバイル両方の呼び出し箇所で共有）のボタン文言。
  // queued（同時実行数上限で順番待ち）とrunning（経過時間つき）を区別する。nullの間は
  // RouteForm側の既定文言（「生成中...」）に委ねる。
  const generationProgressLabel =
    generationProgress?.status === "queued"
      ? "順番待ち..."
      : generationProgress?.status === "running"
        ? `生成中...(${Math.round(generationProgress.elapsedMs / 1000)}秒経過)`
        : undefined;

  // 「ルートを作る」ブロックの中身（天候・アプリ名は常設ヘッダへ移動済み、T36/T37）。
  // デスクトップの<details>専用（改善計画T250でモバイルはヘッダーの操作バーへ出発地点・
  // 距離・生成ボタンを分離済み。改善計画T300でモバイルの結果表示自体も「ルート設定」
  // 「ルート結果」の2タブへ分割したため、デスクトップはその両方を続けて呼ぶことで
  // 従来どおり1つの折りたたみ内に収める）。
  function renderRouteSectionBody() {
    return (
      <>
        <RouteForm
          distance={distanceInput}
          onDistanceChange={setDistanceInput}
          maxRoutes={maxRoutesInput}
          onMaxRoutesChange={setMaxRoutesInput}
          onGenerate={handleGenerate}
          loading={loading}
          progressLabel={generationProgressLabel}
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
  // 生成前に調整できる、常時表示のメイン導線（route_preference・weightOverrideEnabledの
  // 状態はpage.tsx冒頭のstate宣言・handleGenerateのコメント参照）。モバイルの
  // 「ルート設定」タブ、デスクトップの「ルートを作る」ブロック前半から呼ぶ
  // （改善計画T300、旧renderRouteResultsBodyの前半を分離）。
  // 改善計画T419: 見出し「ルート設定」は呼び出し元によって要否が変わる。デスクトップは
  // 外側のDisclosure見出しが「ルートを作る」（このセクションと後続のルート結果の両方を
  // 束ねる大枠）のため、このセクション自身の見出しとして必要。モバイルはBottomSheet自体の
  // title="ルート設定"（下記BottomSheet呼び出し参照）と文言が重複するため、showHeading=false
  // で抑制する（実機フィードバック「見出しが二重に表示される」）。
  function renderRouteSettingsSectionBody(showHeading: boolean = true) {
    return (
      <div className={layerPanelStyles.group}>
        {showHeading && <h2 className={layerPanelStyles.groupTitle}>ルート設定</h2>}
        <RouteSettingsPanel
          hardFilters={hardFilters}
          onHardFiltersChange={setHardFilters}
          routePreference={routePreference}
          onRoutePreferenceChange={setRoutePreference}
          overrideEnabled={weightOverrideEnabled}
          onOverrideEnabledChange={setWeightOverrideEnabled}
          layerVisibility={layerVisibility}
          onLayerToggle={handleLayerToggle}
          hasDetail={hasDetail}
        />
      </div>
    );
  }

  // 改善計画T545フォローアップ（ユーザー指摘「ルートをクリアもルート結果ヘッダの右上
  // 小さくでいい」）: 「ルート結果」見出し脇の情報アイコンと「ルートをクリア」を
  // まとめて1つの右側アクション群にする。デスクトップ（見出し行）・モバイル
  // （BottomSheetのheaderAction）の両方から同じ中身を呼ぶ。routes.length===0の間は
  // どちらの呼び出し元も描画自体をスキップする（デスクトップはrenderRouteOutcomeSectionBody
  // 自体がnullを返す、モバイルは呼び出し側でroutes.lengthを見てheaderActionをundefinedにする）
  // ため、ここでは呼ばれた時点で必ずroutes.length>0という前提でよい。
  function renderRouteResultHeaderActions() {
    return (
      <>
        <FieldLabel label="ルート結果について" description={ROUTE_RESULT_HINT} hideLabel />
        {/* 改善計画T365: 生成済みの候補一覧・地図描画・選択状態だけをリセットする
            （経由地・目的地のピンは対象外、別々のクリア操作として使い分ける）。
            押した瞬間に実行する即実行アクション（タブのような選択状態は持たない）。 */}
        <button type="button" className={styles.outcomeTabAction} onClick={handleRoutesClear}>
          ルートをクリア
        </button>
      </>
    );
  }

  // 生成結果に関する表示（設定変更の警告・候補ごとの内訳・比較表・色分け設定、ルート設定は
  // 含まない）。モバイルの「ルート結果」タブ、デスクトップの「ルートを作る」ブロック後半から
  // 呼ぶ（改善計画T300、旧renderRouteResultsBodyの後半を分離）。ユーザー指示（省スペース化）:
  // 生成前はほぼ何も出さず、生成後は候補ごとの内訳・比較表を「タブで区切って」1画面に収める。
  //
  // 改善計画T545: 「ルート選択（候補一覧+内訳をひとまとめにした1タブ）/比較」という2段の
  // タブ構成をやめ、候補ごとのタブ＋「比較」タブという1段のフラットなタブ列へ再設計した
  // （ユーザー指摘「ルート選択タブは不要、比較タブと同じ形でルートごとタブにして」）。
  // 候補の切り替え（旧RouteList.tsx）とその候補の内訳表示（RouteAxisProfile）を、
  // このタブ列自体が担う——RouteAxisProfileはタブの中身（Tabs.Content）としてのみ現れる。
  //
  // 改善計画T545フォローアップ: showHeadingはrenderRouteSettingsSectionBodyと同じ理由
  // （見出しの二重表示回避）で使い分ける。デスクトップ（既定true）はこのセクション自身の
  // 見出し「ルート結果」＋renderRouteResultHeaderActions()（情報アイコン＋ルートをクリア）を
  // ここで描画する。モバイルはBottomSheet自体がtitle="ルート結果"の見出しを持つため
  // showHeading=false で抑制し、同じrenderRouteResultHeaderActions()をBottomSheetの
  // headerAction propとして呼び出し側（下のJSX）から渡す——「おすすめ度について」
  // 「おすすめ度・総合難易度について」と分かれていた2箇所の説明はROUTE_RESULT_HINT 1本へ、
  // 「ルートをクリア」はタブ列脇からヘッダ右上へ、それぞれ「ルート結果」セクション見出し
  // 1箇所へ集約した（ユーザー実機指摘）。
  function renderRouteOutcomeSectionBody(showHeading: boolean = true) {
    if (routes.length === 0) return null;

    const showComparisonTab = researchEnabled;
    const outerTabValue = comparisonTabActive ? "comparison" : (selectedRouteId ?? routes[0].id);
    // ユーザー指摘（2026-09-03）: 一度「公開軸がすべて表示されない」という指摘を受けて
    // 重みによる絞り込みを撤去したが、その後のユーザー確認により意図は逆で、「ルート設定で
    // ONにした（重み>0の）軸だけを出してほしい」だった（撤去は誤り、原文どおりに戻す）。
    // ユーザー指示: ルート設定パネルでチェックを外した（重み0にした）軸は、この
    // プロファイルからも消す（軸自体の評価が無いためではなく、ユーザーが「見たくない」と
    // 選んだ軸を除く表示上の絞り込み）。axis_contributions自体は重み0の軸を持たない
    // （backend側で既に重み配分へ折り込み済みのため）が、絞り込み自体はaxesの側で行う
    // （RouteAxisProfile内部のaxisContributions!=nullフィルタとは独立）。重みの参照元は
    // filteredRouteStyleModesと同じ「生成時点の重み」（generatedRoutePreference、
    // 未生成時のみライブなroutePreferenceへフォールバック）に揃える。全候補で共通のため、
    // 候補ごとのTabs.Contentループの外で1回だけ計算する。
    const routeWeights = generatedRoutePreference ?? routePreference;
    const visibleAxes = axisCatalog.axes.filter((axis) => (routeWeights[axis.axisId] ?? 0) > 0);

    return (
      <>
        {showHeading && (
          <div className={styles.outcomeSectionHeader}>
            <h2 className={layerPanelStyles.groupTitle}>ルート結果</h2>
            <div className={styles.outcomeSectionHeaderActions}>{renderRouteResultHeaderActions()}</div>
          </div>
        )}
        {conditionsDirty && (
          <p className={styles.dirtyHint}>条件が変更されています。「ルート生成」を押すと反映されます</p>
        )}
        <Tabs.Root
          className={styles.outcomeTabs}
          value={outerTabValue}
          onValueChange={(value) => {
            // 改善計画T550: 候補タブ・比較タブいずれへ切り替えても、以前の候補で
            // クリックしていた区間の選択は引き継がない（別候補のedge_idを指したまま
            // 地図マーカー・内訳が残ると実態と食い違いを起こすため）。
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
                  {/* 改善計画T545フォローアップ（ユーザー指摘「タブ名はもっと簡潔に」）:
                      総合難易度はタブの中身（RouteAxisProfileのスコア行）に既に出ている
                      ため、タブ自体には候補を見分けるための順位・方向・距離だけを表示する
                      （改善計画T548: 候補タブ自体の並び順もこの総合難易度の昇順）。 */}
                  {/* 改善計画T531: 周回生成が8方位固定から軸重み駆動のフロンティア方式へ
                      転換したことに伴い、同じ方位ラベルの候補が複数並びうるようになった
                      （direction_labelは折返し地点の方位から表示専用に導出するだけで、
                      候補選定の基準ではない）。並び順（overall_difficulty昇順）に沿った
                      1始まりの順位番号を先頭に付け、方位が同じ候補どうしも見分けられる
                      ようにする。 */}
                  {/* 改善計画T364: 経由地ルート(route-waypoints)は候補が常に1件で
                      「方位」という概念が無いため、direction_label（固定文言、
                      route_generator.py参照）をそのまま表示し順位番号も付けない。 */}
                  {/* 改善計画T365/T551: 目的地ルート(route-destination-00形式、前方一致)は
                      経由地を伴わなければvia-node方式で複数件になりうる。方位という概念は
                      無いため「方向」は付けないが、複数件を見分けられるよう順位番号は付ける。 */}
                  {NON_DIRECTIONAL_ROUTE_IDS.has(route.id)
                    ? route.direction_label
                    : route.id.startsWith(DESTINATION_ROUTE_ID_PREFIX)
                      ? `${index + 1}. ${route.direction_label}`
                      : `${index + 1}. ${route.direction_label}方向`}{" "}
                  {route.distance_km.toFixed(1)} km
                </Tabs.Trigger>
              ))}
              {/* 比較タブ: researchEnabledの間は常に出す。ComparisonPanel自身が実験
                  スロット2件未満の間は中身を持たない自己ガードを持つ（旧実装から変更なし、
                  ComparisonPanel.tsx参照）ため、ここでスロット件数を重複判定しない。 */}
              {showComparisonTab && (
                <Tabs.Trigger className={styles.outcomeTabTrigger} value="comparison">
                  比較
                </Tabs.Trigger>
              )}
            </Tabs.List>
          </div>
          {routes.map((route) => (
            <Tabs.Content key={route.id} className={styles.outcomeTabPanel} value={route.id}>
              {/* 改善計画T550: 区間がクリックされている間（selectedRouteSegment）は、
                  ルート全体の内訳の代わりにその区間の地点・到達予想時刻＋軸別内訳
                  （AxisContributionBar、ルート全体の内訳と同じ表示部品）を表示する。
                  地図側のDETAIL_LAYER_ID/DETAIL_HIT_LAYER_IDは選択中候補（selectedCandidate）
                  にしか描画されないため、区間クリックは常に現在アクティブなこのタブの
                  ルートに対して起きる（他候補のタブが誤って区間詳細を出すことは無い）。 */}
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
                    axes={visibleAxes}
                    contributions={selectedRouteSegment.segment.axis_contributions}
                    axisColors={axisChipColors}
                  />
                </div>
              ) : (
                <RouteAxisProfile
                  axes={visibleAxes}
                  axisContributions={route.axis_contributions}
                  overallDifficulty={route.overall_difficulty}
                  axisColors={axisChipColors}
                  routeStyleModes={filteredRouteStyleModes}
                  routeStyleModeId={routeStyleModeId}
                  onRouteStyleModeChange={handleRouteModeSelect}
                  hiddenLegendKeys={hiddenRouteLegendKeys}
                  onToggleLegendKey={handleRouteLegendToggle}
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

      {/* モバイル専用の操作バー（改善計画T250）。「ルートを作る」タブを開かないと出発地点の
          確認も生成もできない、という導線の長さが実機フィードバックだったため、天候ヘッダー
          直下に常設し、地図を見ながらでも操作できるようにした。生成ボタンがタブの外に出た
          ことで、失敗時のエラーメッセージが見えなくなる回帰を避けるためここにも表示する
          （生成結果自体は下部「ルート結果」タブ、renderRouteOutcomeSectionBody参照）。 */}
      {isMobile && (
        <div className={styles.mobileActionBar}>
          <RouteForm
            distance={distanceInput}
            onDistanceChange={setDistanceInput}
            maxRoutes={maxRoutesInput}
            onMaxRoutesChange={setMaxRoutesInput}
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
            dedicatedWayValueBoundaries={dedicatedWayValueBoundaries}
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
            routeStyleModes={filteredRouteStyleModes}
            routeStyleModeId={routeStyleModeId}
            hiddenRouteLegendKeys={hiddenRouteLegendKeys}
            onRegionZoomHintChange={setRegionZoomTooWide}
            onViewportChange={handleViewportChange}
            onLayerDataStatusChange={setLayerDataStatus}
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

          <MapColorLegend groups={mapColorLegendGroups} />

          <MapOverlayControls layers={overlayLayers} onToggle={handleLayerToggle} />

          {/* 地図下部中央の行。全レイヤー一括OFFボタン（実機フィードバック「左上の全クリア
              アイコンをスライドバーの左側に移動して」で旧MapOverlayControls左上から移設）+
              時刻依存レイヤーの時刻スライダーを横並びで置く。ボタンはレイヤーの種類を問わず
              常時押せる必要があるため無条件で出し、スライダーは時刻依存レイヤーが1つ以上ON
              のときだけ隣に出す（改善計画T170、設計原則12: 地図の視界を圧迫しない）。 */}
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
            {/* 改善計画T432: キキクル3種は「防災」カテゴリとして共有タイムラインと無関係な
                常時マウントへ変更したため、この条件から除外した（このスライダー自体は
                動かせるが表示に影響しない）。線状降水帯予測マップは「降水」チップ傘下の
                ソースのため、showPrecipitationNowcastで既にカバーされる。 */}
            {(showPrecipitationNowcast || showWindVector || showThunderNowcast || showTornadoNowcast || showLiden) && (
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

          {/* ユーザー要望（2026-08-31、「今は軸毎やレイヤ毎に走行方位が決められるけれど、
              1つでいい」）: 風・勾配それぞれ個別に持っていたコンパス（環境グループの
              bottomControlRow・RouteSettingsPanel内の「走行方位を設定」）を撤去し、地図上の
              単一のアイコン（MapLibreのズーム/回転コントロールの下）1箇所へ集約した。
              「環境」グループ（風penalty gridFill・勾配gridFill）・評価軸（windAxis/
              gradientAxis）のいずれかが表示中の間だけ現れる。 */}
          {(showWindVector || showGradientFill || showWindAxis || showGradientAxis) && !hasDetail && (
            <TravelBearingControl value={travelBearingDeg} onChange={setTravelBearingDeg} />
          )}

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
            heightVh={mobileSheetHeightVh}
            onHeightChange={handleMobileSheetHeightChange}
            onHeightCommit={commitMobileSheetHeight}
          >
            {/* 改善計画T419: BottomSheet自体のtitle="ルート設定"と中身のh2見出しが重複するため、
                ここではshowHeading=falseで内側の見出しを抑制する。 */}
            {renderRouteSettingsSectionBody(false)}
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
            {renderRouteOutcomeSectionBody(false)}
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
