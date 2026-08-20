"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapView from "@/components/Map/MapView";
import BackendStatus from "@/components/BackendStatus";
import DebugPanel from "@/components/DebugPanel/DebugPanel";
import ResearchPanel from "@/components/ResearchPanel/ResearchPanel";
import DebugConsole from "@/components/DebugConsole/DebugConsole";
import SystemStatusPanel from "@/components/SystemStatusPanel/SystemStatusPanel";
import LocationControl from "@/components/LocationControl/LocationControl";
import MapOverlayControls, { type OverlayLayerChip } from "@/components/MapOverlayControls/MapOverlayControls";
import { DeveloperIcon, LogIcon, MapAppearanceIcon, ResearchIcon, RouteIcon, StatusIcon } from "@/components/Map/icons";
import MapLayersPanel from "@/components/MapLayersPanel/MapLayersPanel";
import BottomSheet, { clampSheetHeightVh, DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import {
  MAP_LAYERS,
  type LayerDataStatusByLayer,
  type MapLayerId,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import { RAMP_AXES, axisMapLayerId } from "@/components/Map/axisLayers";
import { SECONDARY_AXES } from "@/components/Map/secondaryAxes";
import { axisMaterialLayerIds, axisMaterials, PRIMARY_ATTRIBUTE_LABELS } from "@/components/Map/primaryAttributes";
import { PREFERENCE_AXES } from "@/lib/evaluationAxes";
import { summarizeLegendFilters, type LegendFilterSummaryAxis } from "@/components/Map/legendFilter";
import {
  ROAD_FILTER_AXES,
  ROAD_LINE_COLOR_AXIS_ID,
  ROAD_LINE_WIDTH_AXIS_ID,
  getRoadFilterAxis,
  type RoadFilterAxisId,
} from "@/components/Map/roadFilterAxes";
import { STATIC_FILTER_AXES, type StaticFilterAxisId } from "@/components/Map/staticAttributeLayers";
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
import RouteForm from "@/components/RouteForm/RouteForm";
import RouteList from "@/components/RouteList/RouteList";
import WeatherPanel from "@/components/WeatherPanel/WeatherPanel";
import DynamicLayerTimeSlider, {
  type DynamicLayerTimeSliderFrame,
} from "@/components/DynamicLayerTimeSlider/DynamicLayerTimeSlider";
import {
  centerFramesAroundLatestObserved,
  fetchNowcastFrames,
  formatNowcastFrameTime,
  latestObservedFrameIndex,
  nearestFrameIndexByTime,
  nowcastTileUrlTemplate,
  parseValidtime,
  type NowcastFrame,
} from "@/components/Map/precipitationNowcast";
import {
  clampWindDetailBbox,
  formatWindFrameTime,
  nearestFrameIndexToNow,
  parseJstTime,
  windGridToCellFeatureCollection,
  windGridToFeatureCollection,
  WIND_DETAIL_MIN_ZOOM,
  WIND_GRID_DETAIL_SPACING_DEG,
  WIND_GRID_SPACING_DEG,
  type MapViewport,
} from "@/components/Map/windLayer";
import type { WindGridPoint } from "@/types/weather";
import WeightPanel, { DEFAULT_ROUTE_PREFERENCE, DEFAULT_SCORING_WEIGHTS } from "@/components/WeightPanel/WeightPanel";
import CarStressRecipePanel from "@/components/CarStressRecipePanel/CarStressRecipePanel";
import {
  DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  DEFAULT_ROAD_SUITABILITY_RECIPE,
  DEFAULT_CAR_STRESS_RECIPE,
} from "@/components/Map/carStressExpression";
import RoadSuitabilityRecipePanel from "@/components/RoadSuitabilityRecipePanel/RoadSuitabilityRecipePanel";
import MotorVehicleDensityRecipePanel from "@/components/MotorVehicleDensityRecipePanel/MotorVehicleDensityRecipePanel";
import ComparisonPanel from "@/components/ComparisonPanel/ComparisonPanel";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useRecipeOverride } from "@/hooks/useRecipeOverride";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useLocation } from "@/hooks/useLocation";
import { useStoredState } from "@/hooks/useStoredState";
import { generateRoutes } from "@/services/routeApi";
import { getCurrentWeather, getWindGrid, getWindGridDetail } from "@/services/weatherApi";
import type {
  Coordinates,
  MotorVehicleDensityRecipeOverride,
  RoadSuitabilityRecipeOverride,
  RouteCandidate,
  RoutePreferenceWeights,
  ScoringWeights,
  CarStressRecipeOverride,
} from "@/types/route";
import type { WeatherConditions } from "@/types/weather";
import { EXPERIMENT_SLOT_COLORS, MAX_EXPERIMENT_SLOTS, type ExperimentSlot } from "@/types/experimentSlot";
import styles from "./page.module.css";

const DISTANCE_TOLERANCE_KM = 5;

// 凡例の絞り込みチェックを地図へ反映するまでの猶予。チェック自体は即時反映が原則
// （T31）だが、連続タップのたびにMapLibreのフィルタ再適用を走らせない（useDebouncedValue参照）。
// 道路情報の2軸に加え、改善計画T63で車ストレス・自転車インフラ・指定路線・停止要因POI・
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

const DEFAULT_LAYER_VISIBILITY: MapLayerVisibility = {
  elevation: false,
  // 改善計画T165: 「道路情報」（road）を論理2レイヤーへ分割。旧保存値（road: boolean）から
  // 両方へ移行する処理はuseStoredStateのdeserialize（下記）参照。
  roadType: false,
  roadSurface: false,
  carStress: false,
  bicycleInfra: false,
  designation: false,
  stopPoi: false,
  supplyPoi: false,
  accidents: false,
  // 改善計画T171: 降水ナウキャスト。初期表示から地図を覆うと視界を圧迫するため既定OFF
  // （設計原則12、他の静的レイヤーと同じ「明示的にONにして初めて出る」規約）。
  precipitationNowcast: false,
  // 改善計画T178: 風の矢印。precipitationNowcastと同じ理由で既定OFF。
  windVector: false,
  route: true,
  // 二次軸rampレイヤー（改善計画T145b）。backendレジストリ生成物（axis-catalog.json）の
  // kind="ramp"軸から自動生成されるため、個別の行を手書きせずカタログから導出する
  // （新しい軸が増えてもこのファイルの編集は不要）。既定はすべてOFF。
  ...Object.fromEntries(RAMP_AXES.map((axis) => [axisMapLayerId(axis.axisId), false])),
};

// 「どのモードでも非表示カテゴリ無し」を表す共通の空配列。useStateの外に置いて参照を
// 固定し、MapView側のエフェクト依存（hidden*LegendKeys）が毎レンダーで発火しないようにする。
const NO_HIDDEN_LEGEND_KEYS: string[] = [];

// 「ルートを作る」セクション見出しのDOM id。デスクトップの<summary>とモバイルのBottomSheetの
// 見出しの両方で使う（両者は排他表示のためid重複しない）。地図の見え方セクション
// （MapLayersPanel）のルート未生成時の案内からの誘導スクロール先でもある。
const GENERATE_SECTION_TITLE_ID = "generate-section-title";
// モバイルの「地図の見え方」シート見出しのDOM id。
const MAP_SETTINGS_SHEET_TITLE_ID = "map-settings-sheet-title";
// モバイルの「研究」シート見出しのDOM id。
const RESEARCH_SHEET_TITLE_ID = "research-sheet-title";
// モバイルの「開発者」シート見出しのDOM id。
const DEVELOPER_SHEET_TITLE_ID = "developer-sheet-title";

type MobileSheet = "route" | "map" | "research" | "developer" | null;

export default function Home() {
  const { location, locationSource, locating, locateError, handleLocateMe } = useLocation();

  const [routes, setRoutes] = useState<RouteCandidate[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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
  } | null>(null);

  // 評価重みのリクエスト上書き（研究インターフェース改善 §10-1/4）。overrideEnabled=falseの間は
  // 生成リクエストからscoring_weights/route_preferenceを省略し、既存挙動（YAML既定値）を
  // 完全に維持する（一般ユーザーには影響しない）。
  const [weightOverrideEnabled, setWeightOverrideEnabled] = useState(false);
  const [scoringWeights, setScoringWeights] = useState<ScoringWeights>(DEFAULT_SCORING_WEIGHTS);
  const [routePreference, setRoutePreference] = useState<RoutePreferenceWeights>(DEFAULT_ROUTE_PREFERENCE);

  // 車の圧迫感・安全度・道路適正・自動車密度の4レシピの上書き状態（有効フラグ・値・地図反映用の
  // デバウンス値）はuseRecipeOverride（改善計画T133）へ集約。各レシピは互いに独立したトグル
  // （レシピは有効化すると地図の色分けに即座に反映されるが、重みは次回のルート生成まで
  // 反映されないという挙動差があるため、ユーザー承認済みで別トグルにしてある。「道路適正」
  // 「自動車密度」は改善計画: 車との近さ材料の共有元化により車の圧迫感・安全度の両方が
  // 共有する材料[domain/recipe.py: car_closeness()]で、上書きすると両軸の地図色・内訳
  // ポップアップ・次回のルート生成すべてへ同時に反映される）。無効の間はMapViewへ
  // undefinedを渡し（既定レシピを使う）、生成リクエストからも対応するrecipeキーを省略する。
  const {
    overrideEnabled: carStressRecipeOverrideEnabled,
    setOverrideEnabled: setCarStressRecipeOverrideEnabled,
    recipe: carStressRecipe,
    setRecipe: setCarStressRecipe,
    debouncedRecipe: debouncedCarStressRecipe,
  } = useRecipeOverride<CarStressRecipeOverride>(DEFAULT_CAR_STRESS_RECIPE, LEGEND_FILTER_DEBOUNCE_MS);

  const {
    overrideEnabled: roadSuitabilityRecipeOverrideEnabled,
    setOverrideEnabled: setRoadSuitabilityRecipeOverrideEnabled,
    recipe: roadSuitabilityRecipe,
    setRecipe: setRoadSuitabilityRecipe,
    debouncedRecipe: debouncedRoadSuitabilityRecipe,
  } = useRecipeOverride<RoadSuitabilityRecipeOverride>(DEFAULT_ROAD_SUITABILITY_RECIPE, LEGEND_FILTER_DEBOUNCE_MS);

  const {
    overrideEnabled: motorVehicleDensityRecipeOverrideEnabled,
    setOverrideEnabled: setMotorVehicleDensityRecipeOverrideEnabled,
    recipe: motorVehicleDensityRecipe,
    setRecipe: setMotorVehicleDensityRecipe,
    debouncedRecipe: debouncedMotorVehicleDensityRecipe,
  } = useRecipeOverride<MotorVehicleDensityRecipeOverride>(
    DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
    LEGEND_FILTER_DEBOUNCE_MS,
  );

  // 実験スロット（研究インターフェース改善 §10-3）: デバッグモード中の生成結果を条件付きで
  // 直近MAX_EXPERIMENT_SLOTS件だけメモリ内に保持し、地図重ね描き・比較表に使う。
  const [experimentSlots, setExperimentSlots] = useState<ExperimentSlot[]>([]);
  const [weather, setWeather] = useState<WeatherConditions | null>(null);
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [weatherError, setWeatherError] = useState<string | null>(null);

  // 下部バー2本（降水ナウキャスト・風）が指す対象時刻（改善計画、実機フィードバック
  // 「同じ日時を示した状態で連動させ、変えるのは感度（スライド時の差）だけ」）。片方の
  // バーを動かすとこの共有時刻が更新され、もう片方のindexもこの時刻へ最も近いフレームへ
  // 追従する（下のnowcastFrameIndex/windFrameIndex参照）。各バー自身の刻み幅（感度）は
  // それぞれのフレーム配列の間隔がそのまま担うため、この時刻自体は連続値のままでよい。
  const [dynamicLayerTargetTime, setDynamicLayerTargetTime] = useState(() => new Date());

  // 降水ナウキャストの時刻一覧（改善計画T170/T171）。フェッチ・更新間隔は
  // layerVisibility.precipitationNowcastがONの間だけ動かすeffect（下記）が管理する。
  // スライダー位置(index)はnowcastFrames自体ではなく共有のdynamicLayerTargetTimeから
  // 都度導出する（下のnowcastFrameIndex参照）ため、ここでは持たない。
  const [nowcastFrames, setNowcastFrames] = useState<NowcastFrame[]>([]);
  const [nowcastLoading, setNowcastLoading] = useState(false);
  const [nowcastError, setNowcastError] = useState<string | null>(null);

  // 風の格子点マップ（改善計画T178フォローアップ、自前実装）の取得結果。上のnowcastFrames
  // と同じ構造・同じ理由（layerVisibility.windVectorがONの間だけ動かすeffectで管理、
  // スライダー位置はdynamicLayerTargetTimeから導出）。
  const [windGrid, setWindGrid] = useState<WindGridPoint[]>([]);
  const [windLoading, setWindLoading] = useState(false);
  const [windError, setWindError] = useState<string | null>(null);
  // 風の詳細格子（改善計画T180、ヒートマップ等の面表現用）。ズームインして狭い範囲を
  // 見ているときだけ、上のwindGrid（関東全域・粗い間隔）を密な間隔の格子で補う。
  // 取得に失敗した場合やまだ無い場合は空配列のままにし、effectiveWindGrid側で
  // windGridへ自動フォールバックする（ユーザーへエラー表示はしない、既にwindGridが
  // ある前提の補助的な機能のため）。
  const [windDetailGrid, setWindDetailGrid] = useState<WindGridPoint[]>([]);
  // MapViewから伝わる現在のビューポート（改善計画T180、MapView.tsx: onViewportChange参照）。
  // moveend/zoomendのたびに素の値が来るため、フェッチ用にはデバウンスして使う
  // （下のwindDetailフェッチeffect参照）。
  const [mapViewport, setMapViewport] = useState<MapViewport | null>(null);

  // 地図レイヤーのON/OFF（MAP_LAYERSのid単位。レイヤーを追加したらDEFAULT_LAYER_VISIBILITYへ
  // 初期値を1つ足す）。localStorageへの保存・復元はuseStoredState（改善計画T47 R-6）参照。
  // 既知のレイヤーIDかつboolean値のものだけ採用する（レイヤーの増減や壊れた保存値があっても、
  // 残りの設定は活かしてデフォルトで埋める）。
  const [layerVisibility, setLayerVisibility] = useStoredState<MapLayerVisibility>(
    LAYER_VISIBILITY_STORAGE_KEY,
    DEFAULT_LAYER_VISIBILITY,
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
        const next = { ...DEFAULT_LAYER_VISIBILITY };
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
  // 限定するため（deserializeがDEFAULT_LAYER_VISIBILITYのキー走査で復元するため、axis:*の
  // キーも既知のレイヤーIDとして保存・復元の対象に自動で含まれる）。
  const axisVisibility = useMemo(
    () =>
      Object.fromEntries(
        RAMP_AXES.map((axis) => {
          const id = axisMapLayerId(axis.axisId);
          return [id, layerVisibility[id] ?? false];
        }),
      ),
    [layerVisibility],
  );
  // 改善計画（2次の下敷きの副作用対応）: 2次（車の圧迫感・ramp軸）を太く半透明な下敷きに
  // するのは、その材料（1次、axisMaterialLayerIds）が1つでも同時に表示されているときだけに
  // する。材料が1つも表示されていなければ、下に隠すものが無いため通常の太さ・不透明度で
  // 表示する（以前は2次をONにした瞬間から常に太く半透明にしていたため、道路網が密な都市部で
  // 下敷きの重なりだけで地図全体がぼやけて見える不具合があった、実機フィードバック）。
  // T167の材料連動ONカスケード（handleLayerToggle）と同じaxisMaterialLayerIdsを使い、
  // 「材料として使われている」の定義を1箇所（primaryAttributes.ts）に保つ。
  const secondaryAxisCasingLayerIds = useMemo(
    () =>
      SECONDARY_AXES.filter((axis) => {
        if (!axis.layerId) return false;
        return axisMaterialLayerIds(axis.axisId).some((materialId) => layerVisibility[materialId]);
      }).map((axis) => axis.layerId as MapLayerId),
    [layerVisibility],
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
  // デバッグログパネル自体の開閉。デバッグモードON＝ログ記録は常時有効だが、パネル表示は
  // 別（常時画面を占有させたくないという実機フィードバックを受け、右上の起動アイコンで
  // 開閉する方式へ変更、モバイル実機フィードバック対応T42）。デフォルト閉。
  const [debugConsoleOpen, setDebugConsoleOpen] = useState(false);
  const [systemStatusOpen, setSystemStatusOpen] = useState(false);

  const debugEnabled = useDebugEnabled();
  const researchEnabled = useResearchEnabled();

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
  // 改善計画T63: 道路情報以外の絞り込み可能レイヤー（車ストレス・自転車インフラ・指定路線・
  // 停止要因POI・事故の当事者/重大度）。roadHiddenKeysByModeと同じ理由でuseMemoにより
  // 参照を安定させる。
  const staticLegendHiddenKeysByAxis = useMemo(
    () =>
      Object.fromEntries(
        STATIC_FILTER_AXES.map((axis) => [axis.axisId, hiddenLegendKeysByMode[axis.axisId] ?? NO_HIDDEN_LEGEND_KEYS]),
      ) as unknown as Record<StaticFilterAxisId, readonly string[]>,
    [hiddenLegendKeysByMode],
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
  // 車の圧迫感・安全度・道路適正・自動車密度レシピの数値入力欄も、地図への反映だけを
  // 同じ猶予でデバウンスする（各パネル自体は即時のrecipeを参照し入力欄の反応は遅らせない。
  // 地図の再描画・T90内訳ポップアップ用のdebouncedRecipeだけが遅延する）。デバウンス自体は
  // useRecipeOverride（改善計画T133）へ集約済み。

  // 改善計画T167: 推定指標レイヤー（車の圧迫感・停止密度・事故密度）をONにしたら、
  // axisMaterials（T164）から導出した材料の観測データレイヤーも連動ONする。MapLayersPanelの
  // 「絞り込みを操作すると自動でON」と同じ片方向パターン（OFFへは連動させない、ユーザーが
  // 個別に隠した観測データレイヤーを推定指標のOFF操作で勝手に消さない）。
  const handleLayerToggle = useCallback(
    (id: MapLayerId, on: boolean) => {
      setLayerVisibility((prev) => {
        const next: MapLayerVisibility = { ...prev, [id]: on };
        if (on) {
          const axis = SECONDARY_AXES.find((a) => a.layerId === id);
          if (axis) {
            for (const materialLayerId of axisMaterialLayerIds(axis.axisId)) {
              next[materialLayerId] = true;
            }
          }
        }
        return next;
      });
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
    const layerIds = new Set(STATIC_FILTER_AXES.map((axis) => axis.layerId));
    for (const layerId of layerIds) {
      const axes = STATIC_FILTER_AXES.filter((axis) => axis.layerId === layerId).map((axis) => ({
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
  }, [staticLegendHiddenKeysByAxis]);

  // 地図上のチップ行はレイヤーカタログ（MAP_LAYERS）から組み立てる。レイヤーを追加したら
  // summaryの対応をここへ1行足すだけでよい（チップ・凡例パネルの描画は汎用）。
  const overlayLayers = useMemo<OverlayLayerChip[]>(
    () =>
      MAP_LAYERS.map((layer) => {
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
                : staticFilterSummaries[layer.id]?.legendDetails;
        return {
          id: layer.id,
          label: layer.label,
          chipLabel: layer.chipLabel ?? layer.label,
          on: layerVisibility[layer.id],
          disabled,
          title: disabled ? "ルートを生成・選択すると使えます" : `${layer.description}[設定はサイドバー]`,
          summary,
          legendDetails,
          // 地図上チップのカテゴリ束ね（改善計画T128、MapOverlayControls.tsx）用。
          category: layer.category,
          dataNature: layer.dataNature,
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
    ],
  );

  // モバイルタブバーのボタン操作。同じタブを再タップしたら閉じる（トグル）。
  const handleMobileTabClick = useCallback((sheet: "route" | "map" | "research" | "developer") => {
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

  useEffect(() => {
    // fetchWeatherForはsetState呼び出しを含むため、effect本体からの直接同期呼び出しを避けて
    // マイクロタスク経由で実行する（react-hooks/set-state-in-effect対策）
    Promise.resolve().then(() => fetchWeatherFor(location));
  }, [location, fetchWeatherFor]);

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
        // 実況（targetTimes_N1）は予測（targetTimes_N2）よりずっと件数が多い（実機確認:
        // 2026-08-20時点で実況37件・約3時間分に対し予測12件・60分分）ため、そのまま
        // スライダーへ渡すと「現在」がトラック上でかなり右寄りになる（実機フィードバック
        // 「時間バーの現況を中央初期表示して」）。centerFramesAroundLatestObservedで
        // 実況側を予測側と同じ件数まで切り詰め、「現在」が常にトラックの中央に来るようにする。
        const frames = centerFramesAroundLatestObserved(await fetchNowcastFrames());
        if (cancelled) return;
        setNowcastFrames(frames);
        setNowcastError(null);
      } catch (error: unknown) {
        if (cancelled) return;
        setNowcastError(error instanceof Error ? error.message : "降水ナウキャストの取得に失敗しました");
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

  // 共有の対象時刻（dynamicLayerTargetTime）に最も近い実況/予測フレームのindex。下部バー
  // 2本の時刻連動（改善計画、実機フィードバック「同じ日時を示した状態で連動させ」）の要。
  // 降水ナウキャストのフレーム間隔は約5分ぶんしかなく（centerFramesAroundLatestObserved
  // 参照）、対象時刻が範囲外（風バー側を遠い未来へ動かした等）になったときは配列の端へ
  // 自然にクランプされる（このフレーム自体にJMAの実データが無い以上、これ以上は追従
  // できない・する意味も無い）。
  const nowcastFrameIndex = useMemo(
    () => nearestFrameIndexByTime(nowcastFrames, dynamicLayerTargetTime),
    [nowcastFrames, dynamicLayerTargetTime]
  );

  const precipitationNowcastTileUrl = useMemo(() => {
    const frame = nowcastFrames[nowcastFrameIndex];
    return frame ? nowcastTileUrlTemplate(frame) : undefined;
  }, [nowcastFrames, nowcastFrameIndex]);

  // 風の格子点マップ（改善計画T178フォローアップ、自前実装）。バックエンド側が30分TTL
  // キャッシュ（weather_client.py）を持つため、それより短い間隔で再取得してもキャッシュ
  // ヒットするだけで新しいデータは得られない。TTLに合わせた間隔で再取得する。
  const WIND_REFRESH_INTERVAL_MS = 30 * 60 * 1000;
  const showWindVector = layerVisibility.windVector;
  useEffect(() => {
    if (!showWindVector) return;
    let cancelled = false;
    const load = async (isFirstLoad: boolean) => {
      if (isFirstLoad) setWindLoading(true);
      try {
        const grid = await getWindGrid();
        if (cancelled) return;
        setWindGrid(grid);
        setWindError(null);
      } catch (error: unknown) {
        if (cancelled) return;
        setWindError(error instanceof Error ? error.message : "風データの取得に失敗しました");
      } finally {
        if (!cancelled && isFirstLoad) setWindLoading(false);
      }
    };
    Promise.resolve().then(() => load(true));
    const intervalId = window.setInterval(() => load(false), WIND_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showWindVector]);

  // 風の詳細格子（改善計画T180）。ズームインして狭い範囲を見ているときだけ、現在の
  // ビューポートに交差する密な格子を取得する。パン・ズームのたびに素の値が来る
  // mapViewportをそのまま使うと1操作で何度もリクエストが飛ぶため、デバウンスしてから使う
  // （道路情報の絞り込み等と同じuseDebouncedValue、LEGEND_FILTER_DEBOUNCE_MSより長め。
  // 地図フィルタの再適用と違いネットワーク往復を伴うため、より鷹揚な間隔にしている）。
  const WIND_DETAIL_VIEWPORT_DEBOUNCE_MS = 500;
  const debouncedMapViewport = useDebouncedValue(mapViewport, WIND_DETAIL_VIEWPORT_DEBOUNCE_MS);
  useEffect(() => {
    let cancelled = false;
    // setState呼び出しを含むため、effect本体からの直接同期呼び出しを避けてマイクロタスク
    // 経由で実行する（react-hooks/set-state-in-effect対策、fetchWeatherForと同じ理由）。
    Promise.resolve().then(async () => {
      if (cancelled) return;
      if (!showWindVector || !debouncedMapViewport || debouncedMapViewport.zoom < WIND_DETAIL_MIN_ZOOM) {
        // ズームアウトした・風レイヤーOFFにした場合は詳細格子を捨てて粗い格子へ戻す
        // （古いズームイン時点の詳細格子が、ズームアウト後もそのまま使われ続けるのを防ぐ）。
        setWindDetailGrid([]);
        return;
      }
      try {
        const grid = await getWindGridDetail(clampWindDetailBbox(debouncedMapViewport));
        if (cancelled) return;
        setWindDetailGrid(grid);
      } catch {
        // 補助的な機能のため、失敗時はエラー表示をせず静かに粗い格子（windGrid）へ
        // フォールバックする（リクエスト自体のログはweatherApi.ts側で既に記録済み）。
        if (cancelled) return;
        setWindDetailGrid([]);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [showWindVector, debouncedMapViewport]);

  // 詳細格子が取得できていればそちらを優先し、無ければ粗い格子（windGrid）を使う。
  const effectiveWindGrid = windDetailGrid.length > 0 ? windDetailGrid : windGrid;

  // 共有の対象時刻に最も近い風フレームのindex（nowcastFrameIndexと同じ理由・同じ設計）。
  // windGrid[0]?.timesを正とする（windCurrentIndex/windSliderFramesと同じ前提、下記参照）。
  // 風は48時間ぶんの時刻幅を持つため、降水ナウキャスト側より広い範囲で追従できる。
  const windFrameIndex = useMemo(
    () => nearestFrameIndexToNow(windGrid[0]?.times ?? [], dynamicLayerTargetTime),
    [windGrid, dynamicLayerTargetTime]
  );

  // 格子点が1件も無い（未取得・全地点取得失敗）間はundefined（MapView側は
  // visible && geoJson != nullで表示するため、フェッチ未完了中に古いフレームが
  // 一瞬見えるのを防ぐ、precipitationNowcastTileUrlと同じ扱い）。
  const windVectorGeoJson = useMemo(
    () => (effectiveWindGrid.length > 0 ? windGridToFeatureCollection(effectiveWindGrid, windFrameIndex) : undefined),
    [effectiveWindGrid, windFrameIndex]
  );

  // 実機フィードバック「どの範囲の風向き・風速を示しているか分かりにくい」対応。
  // effectiveWindGridが詳細格子か粗い格子かで間隔（セルの1辺の長さ）が変わるため、
  // 同じ切り替えロジックで間隔も選ぶ（windDetailGridが使われているならDETAIL、
  // そうでなければ粗い格子のWIND_GRID_SPACING_DEG）。
  const effectiveWindSpacingDeg = windDetailGrid.length > 0 ? WIND_GRID_DETAIL_SPACING_DEG : WIND_GRID_SPACING_DEG;
  const windCellGeoJson = useMemo(
    () =>
      effectiveWindGrid.length > 0
        ? windGridToCellFeatureCollection(effectiveWindGrid, windFrameIndex, effectiveWindSpacingDeg)
        : undefined,
    [effectiveWindGrid, windFrameIndex, effectiveWindSpacingDeg]
  );

  // 地図下部の時刻スライダー（DynamicLayerTimeSlider）へ渡す表示用フレーム列。時刻の
  // 整形・実況/予測ラベルはレイヤー固有のデータ層（precipitationNowcast.ts/windLayer.ts）に
  // 閉じているため、ここで{label, badge}へ変換してからUIコンポーネントへ渡す
  // （DynamicLayerTimeSlider自体はレイヤー固有の時刻形式を知らない汎用コンポーネント）。
  const nowcastSliderFrames = useMemo<DynamicLayerTimeSliderFrame[]>(
    () => nowcastFrames.map((frame) => ({ label: formatNowcastFrameTime(frame.validtime), badge: frame.isForecast ? "予測" : "実況" })),
    [nowcastFrames]
  );
  // 全格子点で共通のはず（同じforecast_days・timezoneで一括取得しているため）の時刻配列を
  // 先頭の格子点から取る（windLayer.ts: nearestFrameIndexToNowの利用箇所と同じ前提）。
  const windSliderFrames = useMemo<DynamicLayerTimeSliderFrame[]>(
    () => (windGrid[0]?.times ?? []).map((time) => ({ label: formatWindFrameTime(time) })),
    [windGrid]
  );

  // 「現在」に戻るボタン（改善計画、実機フィードバック「現況に戻すボタンも横に追加して」）の
  // ジャンプ先index。初回フェッチ時にスライダー位置の初期値として使う値
  // （latestObservedFrameIndex/nearestFrameIndexToNow）と同じ計算だが、ボタンは
  // フェッチのたびではなく毎回押された時点の「現在」に戻したいため、frames自体から
  // 都度計算する派生値として持つ（nowcastFrameIndex/windFrameIndexとは独立）。
  const nowcastCurrentIndex = useMemo(() => latestObservedFrameIndex(nowcastFrames), [nowcastFrames]);
  const windCurrentIndex = useMemo(() => nearestFrameIndexToNow(windGrid[0]?.times ?? []), [windGrid]);

  // 下部バー2本の時刻連動（改善計画、実機フィードバック「同じ日時を示した状態で連動させ、
  // 変えるのは感度（スライド時の差）だけ」）。DynamicLayerTimeSlider自体のonIndexChangeは
  // レイヤー固有のindexしか知らないため、ここでそのレイヤーのフレーム時刻へ変換してから
  // 共有のdynamicLayerTargetTimeへ書き込む（「現在」ボタン＝onIndexChange(currentIndex)の
  // 呼び出しも同じ経路を通るため、別扱い不要）。
  const handleNowcastIndexChange = useCallback(
    (index: number) => {
      const frame = nowcastFrames[index];
      if (frame) setDynamicLayerTargetTime(parseValidtime(frame.validtime));
    },
    [nowcastFrames]
  );
  const handleWindIndexChange = useCallback(
    (index: number) => {
      const time = windGrid[0]?.times[index];
      if (time) setDynamicLayerTargetTime(parseJstTime(time));
    },
    [windGrid]
  );

  // 生成条件のうち重み設定・車ストレスレシピの比較キー（上書き無効時はnull＝
  // バックエンド既定値を表す）。トグルは独立のため、それぞれ個別に無効時null化する。
  const currentWeightsKey = JSON.stringify({
    weights: weightOverrideEnabled ? { scoringWeights, routePreference } : null,
    carStressRecipe: carStressRecipeOverrideEnabled ? carStressRecipe : null,
    roadSuitabilityRecipe: roadSuitabilityRecipeOverrideEnabled ? roadSuitabilityRecipe : null,
    motorVehicleDensityRecipe: motorVehicleDensityRecipeOverrideEnabled ? motorVehicleDensityRecipe : null,
  });

  // 表示中の候補の生成条件と現在のフォーム値がずれているか（生成条件系は「生成ボタンで
  // 反映」のため、編集しただけでは何も起きない。それをヒントとして可視化する、T31）
  const conditionsDirty =
    generatedConditions != null &&
    routes.length > 0 &&
    (location.latitude !== generatedConditions.latitude ||
      location.longitude !== generatedConditions.longitude ||
      Number(distanceInput) !== generatedConditions.distanceKm ||
      currentWeightsKey !== generatedConditions.weightsKey);

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
        ...(carStressRecipeOverrideEnabled ? { car_stress_recipe: carStressRecipe } : {}),
        ...(roadSuitabilityRecipeOverrideEnabled ? { road_suitability_recipe: roadSuitabilityRecipe } : {}),
        ...(motorVehicleDensityRecipeOverrideEnabled
          ? { motor_vehicle_density_recipe: motorVehicleDensityRecipe }
          : {}),
      });
      setRoutes(candidates);
      setSelectedRouteId(candidates[0]?.id ?? null);
      // dirty判定の基準は「いま表示している候補を作った条件」。エラー時は既存候補が
      // 残るため更新しない（tryの成功パスでのみ更新する）
      setGeneratedConditions({
        latitude: location.latitude,
        longitude: location.longitude,
        distanceKm,
        weightsKey: currentWeightsKey,
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
      setErrorMessage(error instanceof Error ? error.message : "不明なエラーが発生しました");
    } finally {
      setLoading(false);
    }
  }

  // 「ルートを作る」ブロックの中身（天候・アプリ名は常設ヘッダへ移動済み、T36/T37。
  // デスクトップの<details>とモバイルのBottomSheetの両方から呼ぶ、モバイル実機
  // フィードバック対応T34）。
  function renderRouteSectionBody() {
    return (
      <>
        <LocationControl location={location} source={locationSource} />

        <RouteForm
          distance={distanceInput}
          onDistanceChange={setDistanceInput}
          onGenerate={handleGenerate}
          loading={loading}
        />
        {conditionsDirty && (
          <p className={styles.dirtyHint}>条件が変更されています。「ルート生成」を押すと反映されます</p>
        )}
        {errorMessage && <ErrorText>{errorMessage}</ErrorText>}
        {/* 生成前の空状態には「まず何をするか」のガイドを出す（初見ユーザー向け、T30） */}
        {routes.length === 0 && !loading && !errorMessage && (
          <p className={styles.emptyHint}>
            距離を入れて「ルート生成」を押すと、周回ルートの候補が地図に表示されます
          </p>
        )}
        <RouteList routes={routes} selectedRouteId={selectedRouteId} onSelect={setSelectedRouteId} />
        {/* 実験スロット比較表（研究インターフェース改善 §10-3）。研究モード中の生成が
            2件以上たまったときだけ表示する。生成結果の一覧という性質上、入力パラメータ
            （評価重み・車ストレスレシピ、renderResearchSectionBody参照）とは分け、
            RouteListの並びであるこのブロックに残す。 */}
        {researchEnabled && <ComparisonPanel slots={experimentSlots} />}
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
            <div role="radiogroup" aria-label="ルートの色分け" className={layerPanelStyles.modeGroup}>
              {ROUTE_STYLE_MODES.map((mode) => (
                <button
                  key={mode.id}
                  type="button"
                  role="radio"
                  aria-checked={mode.id === routeStyleModeId}
                  onClick={() => handleRouteModeSelect(mode.id)}
                  className={
                    mode.id === routeStyleModeId
                      ? `${layerPanelStyles.modeItem} ${layerPanelStyles.modeItemActive}`
                      : layerPanelStyles.modeItem
                  }
                >
                  {mode.label}
                </button>
              ))}
            </div>
            <div className={layerPanelStyles.legendCheckboxList}>
              {routeStyleMode.legend.map((entry) => {
                const visible = !hiddenRouteLegendKeys.includes(entry.key);
                const rowClassName = entry.isFallback
                  ? `${layerPanelStyles.legendCheckboxRow} ${layerPanelStyles.legendCheckboxRowFallback}`
                  : layerPanelStyles.legendCheckboxRow;
                return (
                  <label key={entry.key} className={rowClassName}>
                    <input
                      type="checkbox"
                      checked={visible}
                      onChange={() => handleRouteLegendToggle(entry.key)}
                    />
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

  // 「研究」ブロックの中身（研究モードのトグルと、それが有効化する調整パネル2つ）。
  // 元は研究モードトグルを「設定」ブロックへ、パネル自体を「ルートを作る」ブロックへ
  // 分けて置いていたが、評価重み・車ストレスレシピは生成時にも地図描画時にも使う
  // 横断的パラメータでどちらの子でもなく、かつスマホでは2つが別タブに分かれるため
  // 「設定タブでONにしても効果がどこに出るか分からない」という実機フィードバックを受け、
  // トグルと効果を同じブロックへ同居させる独立ブロックへ切り出した
  // （改善計画: 研究パラメータの導線改善）。ComparisonPanel（生成結果の一覧）は
  // renderRouteSectionBody側に残る（上記コメント参照）。
  // 区間難易度の重み（2次要素）のうち、一次情報→二次情報の変換式（レシピ）を個別に持つ軸の
  // 差し込み内容。現状は車の圧迫感のみ（自転車インフラ等、将来レシピ化が広がる軸が増えたら
  // ここへケースを足す）。WeightPanel.renderPreferenceFieldExtra経由で車の圧迫感の重み行の
  // すぐ下に差し込まれる（改善計画: 研究タブを2次要素ごとに整理。以前は「評価の重み」
  // 「レシピ」という別カテゴリに分かれ、同じ軸の重みとレシピを見比べるのに2箇所を
  // 行き来する必要があった）。
  function renderCarStressRecipeExtra() {
    if (!researchEnabled) return null;
    return (
      <>
        {/* 道路適正・自動車密度は車の圧迫感が参照する材料（domain/recipe.py:
            car_closeness()、改善計画: 車との近さ材料の共有元化。かつては安全度軸とも
            共有していたが、安全度はT139で軸ごと廃止済み）。フラットな3パネル並びからは
            「材料→材料を使う軸」の関係が伝わりにくいという統合レビュー指摘（改善計画T133）を
            受け、この2枚を枠付きの「共有材料」グループへまとめ、それを参照する車の圧迫感の
            レシピパネルはインデントして下に続ける。編集内容は参照する側のパネルの
            参照セクションへ即座に反映される。 */}
        <div className={styles.recipeSharedMaterialGroup}>
          <p className={styles.recipeSharedMaterialHeading}>
            レシピ[一次情報→二次情報の変換式]・共有材料[車の圧迫感が参照]
          </p>
          <div className={styles.legendCard}>
            <RoadSuitabilityRecipePanel
              overrideEnabled={roadSuitabilityRecipeOverrideEnabled}
              onOverrideEnabledChange={setRoadSuitabilityRecipeOverrideEnabled}
              recipe={roadSuitabilityRecipe}
              onRecipeChange={setRoadSuitabilityRecipe}
            />
          </div>
          <div className={styles.legendCard}>
            <MotorVehicleDensityRecipePanel
              overrideEnabled={motorVehicleDensityRecipeOverrideEnabled}
              onOverrideEnabledChange={setMotorVehicleDensityRecipeOverrideEnabled}
              recipe={motorVehicleDensityRecipe}
              onRecipeChange={setMotorVehicleDensityRecipe}
            />
          </div>
        </div>
        <div className={styles.recipeDependentAxes}>
          {/* 車ストレスレシピパネル（改善計画: 車ストレスレシピ調整UIパネル、T107の次
              ラウンド）。上のWeightInput（重み）とは独立したトグル（地図の色分けへ
              即時反映される点が重みの上書きと挙動が異なるため）。少車線道路(F)のみを持つ
              薄いパネルになり、先頭に道路適正・自動車密度の現在値（上書き中ならその値、
              無効なら既定値）を読み取り専用で表示する参照セクションを持つ。 */}
          <div className={styles.legendCard}>
            <CarStressRecipePanel
              overrideEnabled={carStressRecipeOverrideEnabled}
              onOverrideEnabledChange={setCarStressRecipeOverrideEnabled}
              recipe={carStressRecipe}
              onRecipeChange={setCarStressRecipe}
              roadSuitabilityRecipe={
                roadSuitabilityRecipeOverrideEnabled ? roadSuitabilityRecipe : DEFAULT_ROAD_SUITABILITY_RECIPE
              }
              motorVehicleDensityRecipe={
                motorVehicleDensityRecipeOverrideEnabled
                  ? motorVehicleDensityRecipe
                  : DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE
              }
            />
          </div>
        </div>
      </>
    );
  }

  // 改善計画T168: axisMaterials（T164）の逆導出を評価側へ適用する。区間難易度の重み行の
  // 直下へ、その軸が参照する一次属性の一覧（正式命名、PRIMARY_ATTRIBUTE_LABELS）を出す。
  // 地図側（T167のPRIMARY_ATTRIBUTE_CHIP_LABELS、地図チップの制約で略名）とは異なり、
  // 研究タブはサイドバー・研究タブ=正式命名の使い分け規則（改善計画T166確定命名表）に従う。
  function renderAxisMaterialsExtra(axisId: string) {
    const materials = axisMaterials(axisId);
    if (materials.length === 0) return null;
    return (
      <p className={styles.recipeSharedMaterialHeading}>
        材料: {materials.map((attrId) => PRIMARY_ATTRIBUTE_LABELS[attrId]).join("・")}
      </p>
    );
  }

  function renderPreferenceFieldExtra(weightKey: keyof RoutePreferenceWeights) {
    const axisId = PREFERENCE_AXES.find((axis) => axis.weightKey === weightKey)?.axisId;
    return (
      <>
        {axisId && renderAxisMaterialsExtra(axisId)}
        {weightKey === "car_stress_weight" && renderCarStressRecipeExtra()}
      </>
    );
  }

  function renderResearchSectionBody() {
    return (
      <>
        <ResearchPanel />

        {/* 「評価の重み」1カテゴリのみ（改善計画: 研究タブを2次要素ごとに整理。以前は
            重み[WeightPanel]とレシピ[CarStressRecipePanel等]を別カテゴリの見出しで分けて
            いたが、同じ軸を調整するのに2箇所を行き来させる構成だった。区間難易度の重み
            [PREFERENCE_FIELDS]は route_preference.yaml の各軸[2次要素]と1:1対応するため、
            レシピを持つ軸[現状は車の圧迫感のみ]はその軸の重み行の直下へ差し込む
            [WeightPanel.renderPreferenceFieldExtra]構成にした）。見出しの見た目は
            MapLayersPanel.tsxのカテゴリ見出し（道路状態/交通・安全等）と同じ発想
            （styles.researchCategoryHeadingがcomposesで再利用）。 */}
        <div className={styles.researchCategory}>
          <h3 className={styles.researchCategoryHeading}>評価の重み</h3>
          {/* 評価重みパネル（研究インターフェース改善Phase2 §10-1/4）。 */}
          {researchEnabled && (
            <div className={styles.legendCard}>
              <WeightPanel
                overrideEnabled={weightOverrideEnabled}
                onOverrideEnabledChange={setWeightOverrideEnabled}
                scoringWeights={scoringWeights}
                onScoringWeightsChange={setScoringWeights}
                routePreference={routePreference}
                onRoutePreferenceChange={setRoutePreference}
                renderPreferenceFieldExtra={renderPreferenceFieldExtra}
              />
            </div>
          )}
        </div>
      </>
    );
  }

  // 「地図の見え方」の中身。開発者向け機能はrenderDeveloperSectionBody（独立した
  // 「開発者」ブロック、旧称「設定」）へ分離済み（一般ユーザーは使わないログ起動を地図上の
  // アイコンから追い出した際に、「地図の見え方」内の折りたたみからも独立ブロックへ
  // 格上げした、T43）。
  function renderMapSettingsSectionBody() {
    return (
      <div className={styles.legendCard}>
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
        />
      </div>
    );
  }

  // 「開発者」ブロック（旧称「設定」、改善計画: 研究パラメータの導線改善でユーザー指摘を
  // 受け改名。「設定」は元々研究モードのトグルも含む何でも入れ場所だった名残の名前で、
  // トグルを「研究」ブロックへ分離した後は一般ユーザー向けの環境設定が一切無い、純粋な
  // 開発者/運用ツール集になっていたため実態に合わせた）の中身: ログ・システム状況・
  // 疎通確認・キャッシュ更新など、一般ユーザーは触らない開発者向け機能をまとめる。
  // デバッグログの起動ボタンは、デバッグモード（DebugPanelのチェック）がONのときだけ
  // 現れる（以前の地図上trailingButtonと同じ条件。ログの記録自体がチェックボックス依存の
  // ため）。システム状況（commit・起動日時・外部API呼出サマリ）はデバッグログの記録有無と
  // 無関係に確認したい情報のため、常時表示のボタンにしている。チェックボックスと同じ
  // debugControl内に置いてnowrapにすることで、他のsystemRow項目と並んで縦積みの
  // 「メニュー」に見えないようにしている。アイコンのみのボタンにしているのも、隣に文言を
  // 並べる冗長さを避けるため。起動すると地図に浮かぶ独立したフローティングパネルが開く
  // （T43）。ログ本文（DebugConsole）とシステム状況（SystemStatusPanel）は情報源・
  // 更新頻度が異なるため別パネルに分離した（2026-08-16、ユーザーFB「中身が混ざって
  // 見にくい」）。
  function renderDeveloperSectionBody() {
    return (
      <>
        <div className={styles.systemRow}>
          <div className={styles.debugControl}>
            <DebugPanel />
            {debugEnabled && (
              <button
                type="button"
                onClick={() => setDebugConsoleOpen((v) => !v)}
                aria-pressed={debugConsoleOpen}
                aria-label={debugConsoleOpen ? "デバッグログを隠す" : "デバッグログを表示"}
                title={debugConsoleOpen ? "デバッグログを隠す" : "デバッグログを表示"}
                className={styles.panelToggleButton}
              >
                <LogIcon size={14} />
              </button>
            )}
            <button
              type="button"
              onClick={() => setSystemStatusOpen((v) => !v)}
              aria-pressed={systemStatusOpen}
              aria-label={systemStatusOpen ? "システム状況を隠す" : "システム状況を表示"}
              title={systemStatusOpen ? "システム状況を隠す" : "システム状況を表示"}
              className={styles.panelToggleButton}
            >
              <StatusIcon size={14} />
            </button>
          </div>
          <BackendStatus />
        </div>
        {/* 基礎地図・道路情報タイルのキャッシュ更新は日常操作ではない運用ボタン */}
        <button type="button" onClick={() => setRefreshToken((v) => v + 1)} className={styles.refreshButton}>
          地図データを再読み込み
        </button>
      </>
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
      </header>

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
                    「B. 地図の見え方（表示系・即時反映）」「研究（評価重み・車ストレスレシピの
                    上書き）」「C. 開発者（運用/デバッグツール、旧称「設定」）」の4ブロック構成
                    （UI一貫性再編T30、地図上のログアイコン廃止に伴い開発者向けをBから
                    独立ブロックへ格上げ、T43）。生成に効く条件（出発地点・距離・重み）が
                    画面のあちこちに分散していた状態を解消し、系統ごとに反映タイミングを揃える。
                    「研究」ブロックは元々、トグル自体を「設定」ブロックへ・調整パネルをAブロックへ
                    分けて置いていたが、評価重み・車ストレスレシピは生成時にも地図描画時にも
                    使う横断的パラメータでA/Bどちらの子でもなく、スマホでは2つが別タブに
                    分かれるため「設定タブでONにしても効果がどこに出るか分からない」という
                    実機フィードバックを受け、トグルと効果を同居させる独立ブロックへ切り出した。
                    切り出した後の「設定」ブロックには研究モード関連が一切残らず開発者/運用
                    ツールのみになったため、「設定」から「開発者」へ改名した（いずれも改善計画:
                    研究パラメータの導線改善）。 */}

                {/* A. ルートを作る: アプリの主機能のため最上部・デフォルト開。このブロック内の
                    編集は生成ボタンを押すまで地図へ影響しない（評価重み・車ストレスレシピの
                    上書きは独立した「研究」ブロックにあり、この契約の対象外）。 */}
                <details
                  className={styles.blockSection}
                  open={generateOpen}
                  onToggle={(e) => setGenerateOpen(e.currentTarget.open)}
                >
                  <summary id={GENERATE_SECTION_TITLE_ID} className={styles.blockSummary}>
                    ルートを作る
                  </summary>
                  <div className={styles.blockBody}>{renderRouteSectionBody()}</div>
                </details>

                {/* B. 地図の見え方: レイヤーのON/OFF・凡例・絞り込み・色分けの設定はすべてここ。
                    地図の上（MapOverlayControls）にはON/OFFチップと適用中の条件の1行サマリだけを
                    残し、詳細は地図に重ねない（地図の視界を優先）。サマリのタップでこのパネルの
                    該当セクションへスクロールしてくる。 */}
                <section className={styles.blockSection}>
                  <h2 className={styles.blockHeading}>地図の見え方</h2>
                  {renderMapSettingsSectionBody()}
                </section>

                {/* 研究: 研究モードのトグルと、それが有効化する評価重み・車ストレスレシピの
                    調整パネル。一般ユーザーは通常触らないためデフォルト閉の折りたたみにする
                    （開発者ブロックと同じ扱い）。 */}
                <details className={styles.blockSection}>
                  <summary className={styles.blockSummary}>研究</summary>
                  <div className={styles.blockBody}>{renderResearchSectionBody()}</div>
                </details>

                {/* C. 開発者（旧称「設定」）: デバッグログ起動・疎通確認・キャッシュ更新など、
                    一般ユーザーは通常触らない運用/デバッグツール。デフォルト閉の折りたたみに
                    する（T30・T43）。 */}
                <details className={styles.blockSection}>
                  <summary className={styles.blockSummary}>開発者</summary>
                  <div className={styles.blockBody}>{renderDeveloperSectionBody()}</div>
                </details>
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
            showPrecipitationNowcast={showPrecipitationNowcast}
            precipitationNowcastTileUrl={precipitationNowcastTileUrl}
            showWindVector={showWindVector}
            windVectorGeoJson={windVectorGeoJson}
            windCellGeoJson={windCellGeoJson}
            showRoadType={layerVisibility.roadType}
            showRoadSurface={layerVisibility.roadSurface}
            showCarStress={layerVisibility.carStress}
            showBicycleInfra={layerVisibility.bicycleInfra}
            carStressRecipe={carStressRecipeOverrideEnabled ? debouncedCarStressRecipe : undefined}
            roadSuitabilityRecipe={
              roadSuitabilityRecipeOverrideEnabled ? debouncedRoadSuitabilityRecipe : undefined
            }
            motorVehicleDensityRecipe={
              motorVehicleDensityRecipeOverrideEnabled ? debouncedMotorVehicleDensityRecipe : undefined
            }
            showDesignation={layerVisibility.designation}
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
          />

          <MapOverlayControls layers={overlayLayers} onToggle={handleLayerToggle} />

          {/* 時刻依存レイヤーが1つ以上ONのときだけ地図上へ出す（改善計画T170、設計原則12:
              地図の視界を圧迫しない）。複数同時ONのときはdynamicLayerSlidersコンテナ
              （page.module.css）が縦積みにする。 */}
          {(showPrecipitationNowcast || showWindVector) && (
            <div className={styles.dynamicLayerSliders}>
              {showPrecipitationNowcast && (
                <DynamicLayerTimeSlider
                  frames={nowcastSliderFrames}
                  index={nowcastFrameIndex}
                  onIndexChange={handleNowcastIndexChange}
                  currentIndex={nowcastCurrentIndex}
                  loading={nowcastLoading}
                  loadingLabel="降水ナウキャストの時刻を取得中..."
                  error={nowcastError}
                  ariaLabel="降水ナウキャストの表示時刻"
                />
              )}
              {showWindVector && (
                <DynamicLayerTimeSlider
                  frames={windSliderFrames}
                  index={windFrameIndex}
                  onIndexChange={handleWindIndexChange}
                  currentIndex={windCurrentIndex}
                  loading={windLoading}
                  loadingLabel="風データの時刻を取得中..."
                  error={windError}
                  ariaLabel="風の表示時刻"
                />
              )}
            </div>
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

          {/* デバッグログ・システム状況の起動は「開発者」ブロック内のボタン
              （renderDeveloperSectionBody）から。position: fixedの独立フローティングパネルの
              ためDOM上の位置は表示に影響しない。 */}
          <DebugConsole open={debugConsoleOpen} onClose={() => setDebugConsoleOpen(false)} />
          <SystemStatusPanel open={systemStatusOpen} onClose={() => setSystemStatusOpen(false)} />
        </div>
      </div>

      {/* モバイル: サイドバーの全面ドロワーだった旧UIを、下部タブバー＋部分シート4枚へ置換
          （モバイル実機フィードバック対応T34、開発者向け機能の独立ブロック化に伴い
          「設定」タブを追加、T43。評価重み・車ストレスレシピのトグルと調整パネルが
          別タブに分かれていて分かりにくいという実機フィードバックを受け「研究」タブを追加、
          切り出し後の「設定」タブが開発者/運用ツールのみになったため「開発者」へ改名
          （いずれも改善計画: 研究パラメータの導線改善）。各タブはアイコン+1行ラベル
          （地図上のiconChip、MapOverlayControls.module.cssと同じ構成）。文字だけだと
          「開発者」が4rem幅ボタン内で折り返され読みにくいという実機フィードバックを受けて
          アイコン化した。「研究」「開発者」は一般ユーザーが日常的に使う2タブより控えめな幅に
          する（tabButtonSmall）。シート表示中も地図の上側が見えたままパン/ズームできる
          （暗幕なし、詳細はBottomSheetのコメント参照）。 */}
      {isMobile && (
        <>
          <nav className={styles.mobileTabBar} aria-label="パネル切り替え">
            <button
              type="button"
              aria-pressed={mobileSheet === "route"}
              onClick={() => handleMobileTabClick("route")}
              className={mobileSheet === "route" ? `${styles.tabButton} ${styles.tabButtonActive}` : styles.tabButton}
            >
              <RouteIcon />
              <span className={styles.tabLabel}>ルートを作る</span>
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
            <button
              type="button"
              aria-pressed={mobileSheet === "research"}
              onClick={() => handleMobileTabClick("research")}
              className={
                mobileSheet === "research"
                  ? `${styles.tabButton} ${styles.tabButtonSmall} ${styles.tabButtonActive}`
                  : `${styles.tabButton} ${styles.tabButtonSmall}`
              }
            >
              <ResearchIcon />
              <span className={styles.tabLabel}>研究</span>
            </button>
            <button
              type="button"
              aria-pressed={mobileSheet === "developer"}
              onClick={() => handleMobileTabClick("developer")}
              className={
                mobileSheet === "developer"
                  ? `${styles.tabButton} ${styles.tabButtonSmall} ${styles.tabButtonActive}`
                  : `${styles.tabButton} ${styles.tabButtonSmall}`
              }
            >
              <DeveloperIcon />
              <span className={styles.tabLabel}>開発者</span>
            </button>
          </nav>

          <BottomSheet
            open={mobileSheet === "route"}
            onClose={() => setMobileSheet(null)}
            title="ルートを作る"
            titleId={GENERATE_SECTION_TITLE_ID}
            heightVh={mobileSheetHeightVh}
            onHeightChange={handleMobileSheetHeightChange}
            onHeightCommit={commitMobileSheetHeight}
          >
            {renderRouteSectionBody()}
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

          <BottomSheet
            open={mobileSheet === "research"}
            onClose={() => setMobileSheet(null)}
            title="研究"
            titleId={RESEARCH_SHEET_TITLE_ID}
            heightVh={mobileSheetHeightVh}
            onHeightChange={handleMobileSheetHeightChange}
            onHeightCommit={commitMobileSheetHeight}
          >
            {renderResearchSectionBody()}
          </BottomSheet>

          <BottomSheet
            open={mobileSheet === "developer"}
            onClose={() => setMobileSheet(null)}
            title="開発者"
            titleId={DEVELOPER_SHEET_TITLE_ID}
            heightVh={mobileSheetHeightVh}
            onHeightChange={handleMobileSheetHeightChange}
            onHeightCommit={commitMobileSheetHeight}
          >
            {renderDeveloperSectionBody()}
          </BottomSheet>
        </>
      )}
    </div>
  );
}
