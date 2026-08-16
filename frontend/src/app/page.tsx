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
import { LogIcon, StatusIcon } from "@/components/Map/icons";
import MapLayersPanel from "@/components/MapLayersPanel/MapLayersPanel";
import BottomSheet, { clampSheetHeightVh, DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import { MAP_LAYERS, type MapLayerId, type MapLayerVisibility } from "@/components/Map/mapLayers";
import { summarizeLegendFilters, type LegendFilterSummaryAxis } from "@/components/Map/legendFilter";
import { ROAD_FILTER_AXES, type RoadFilterAxisId } from "@/components/Map/roadFilterAxes";
import { STATIC_FILTER_AXES, type StaticFilterAxisId } from "@/components/Map/staticAttributeLayers";
import { getRouteStyleMode } from "@/components/Map/routeStyleModes";
import {
  DEFAULT_ROUTE_STYLE_MODE_ID,
  isRouteStyleModeId,
  type RouteStyleModeId,
} from "@/components/Map/routeStyleModes";
import ErrorText from "@/components/ErrorText/ErrorText";
import RouteForm from "@/components/RouteForm/RouteForm";
import RouteList from "@/components/RouteList/RouteList";
import WeatherPanel from "@/components/WeatherPanel/WeatherPanel";
import WeightPanel, { DEFAULT_ROUTE_PREFERENCE, DEFAULT_SCORING_WEIGHTS } from "@/components/WeightPanel/WeightPanel";
import ComparisonPanel from "@/components/ComparisonPanel/ComparisonPanel";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useDebugEnabled } from "@/hooks/useDebugLog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useLocation } from "@/hooks/useLocation";
import { useStoredState } from "@/hooks/useStoredState";
import { generateRoutes } from "@/services/routeApi";
import { getCurrentWeather } from "@/services/weatherApi";
import type { Coordinates, RouteCandidate, RoutePreferenceWeights, ScoringWeights } from "@/types/route";
import type { WeatherConditions } from "@/types/weather";
import { EXPERIMENT_SLOT_COLORS, MAX_EXPERIMENT_SLOTS, type ExperimentSlot } from "@/types/experimentSlot";
import styles from "./page.module.css";

const DISTANCE_TOLERANCE_KM = 5;

// 凡例の絞り込みチェックを地図へ反映するまでの猶予。チェック自体は即時反映が原則
// （T31）だが、連続タップのたびにMapLibreのフィルタ再適用を走らせない（useDebouncedValue参照）。
// 道路情報の2軸に加え、改善計画T63で交通ストレス・自転車インフラ・指定路線・停止要因POI・
// 交差点密度・事故（当事者/重大度）の絞り込みにも同じ猶予を適用する。
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
  road: false,
  trafficStress: false,
  bicycleInfra: false,
  designation: false,
  stopPoi: false,
  intersections: false,
  accidents: false,
  route: true,
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
// モバイルの「設定」シート見出しのDOM id。
const SETTINGS_SHEET_TITLE_ID = "settings-sheet-title";

type MobileSheet = "route" | "map" | "settings" | null;

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

  // 実験スロット（研究インターフェース改善 §10-3）: デバッグモード中の生成結果を条件付きで
  // 直近MAX_EXPERIMENT_SLOTS件だけメモリ内に保持し、地図重ね描き・比較表に使う。
  const [experimentSlots, setExperimentSlots] = useState<ExperimentSlot[]>([]);
  const [weather, setWeather] = useState<WeatherConditions | null>(null);
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [weatherError, setWeatherError] = useState<string | null>(null);

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
        for (const id of Object.keys(next) as MapLayerId[]) {
          const value = (parsed as Record<string, unknown>)[id];
          if (typeof value === "boolean") next[id] = value;
        }
        return next;
      },
    },
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
  // 改善計画T63: 道路情報以外の絞り込み可能レイヤー（交通ストレス・自転車インフラ・指定路線・
  // 停止要因POI・交差点密度・事故の当事者/重大度）。roadHiddenKeysByModeと同じ理由でuseMemoにより
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

  // 地図への反映だけデバウンスする（チェックボックス・条件サマリは即時のroadHiddenKeysByMode/
  // staticLegendHiddenKeysByAxisを参照し、MapViewのフィルタ再適用のみ連続タップを1回へまとめる）。
  const debouncedRoadHiddenKeysByMode = useDebouncedValue(roadHiddenKeysByMode, LEGEND_FILTER_DEBOUNCE_MS);
  const debouncedStaticLegendHiddenKeysByAxis = useDebouncedValue(
    staticLegendHiddenKeysByAxis,
    LEGEND_FILTER_DEBOUNCE_MS,
  );

  const handleLayerToggle = useCallback(
    (id: MapLayerId, on: boolean) => {
      setLayerVisibility((prev) => ({ ...prev, [id]: on }));
    },
    [setLayerVisibility],
  );

  // 地図上（MapOverlayControls）のサマリ行に出す「適用中の条件」の1行要約。
  // 路面はズーム不足の案内を絞り込みより優先する（ONにしたのに何も出ない状態の説明が先）。
  const roadFilterSummary = useMemo(
    () =>
      summarizeLegendFilters(
        ROAD_FILTER_AXES.map((axis) => ({
          label: axis.label,
          legend: axis.legend,
          hiddenKeys: roadHiddenKeysByMode[axis.id] ?? NO_HIDDEN_LEGEND_KEYS,
        })),
      ),
    [roadHiddenKeysByMode],
  );
  const roadSummary = regionZoomTooWide ? "ズームインすると表示されます" : roadFilterSummary;
  // ▶を開いたときの内訳パネル（1行要約だけでは何が起きているか分からないという
  // 実機フィードバックへの対応）用に、軸ごとの全カテゴリ（表示中/非表示問わず）を渡す。
  // ズーム不足で絞り込み自体が無意味なときは空にし、案内文（roadSummary）だけを見せる。
  const roadLegendDetails = useMemo<LegendFilterSummaryAxis[]>(
    () =>
      regionZoomTooWide
        ? []
        : ROAD_FILTER_AXES.map((axis) => ({
            label: axis.label,
            legend: axis.legend,
            hiddenKeys: roadHiddenKeysByMode[axis.id] ?? NO_HIDDEN_LEGEND_KEYS,
          })),
    [regionZoomTooWide, roadHiddenKeysByMode],
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
          layer.id === "road"
            ? roadSummary
            : layer.id === "route"
              ? routeSummary
              : (staticFilterSummaries[layer.id]?.summary ?? null);
        const legendDetails =
          layer.id === "road"
            ? roadLegendDetails
            : layer.id === "route"
              ? routeLegendDetails
              : staticFilterSummaries[layer.id]?.legendDetails;
        return {
          id: layer.id,
          label: layer.label,
          chipLabel: layer.chipLabel ?? layer.label,
          on: layerVisibility[layer.id],
          disabled,
          title: disabled ? "ルートを生成・選択すると使えます" : `${layer.description}（設定はサイドバー）`,
          summary,
          legendDetails,
        };
      }),
    [
      hasDetail,
      layerVisibility,
      roadLegendDetails,
      roadSummary,
      routeLegendDetails,
      routeSummary,
      staticFilterSummaries,
    ],
  );

  // 「地図の見え方」内のルート未生成案内から「ルートを作る」へ誘導する。デスクトップは
  // 該当ブロックを開き、モバイルは「ルートを作る」シートを開く。開いた後の再レンダーを
  // 待ってから（次フレームで）スクロール・フォーカスする。
  const handleGoToGenerate = useCallback(() => {
    if (isMobile) {
      setMobileSheet("route");
    } else {
      setGenerateOpen(true);
    }
    requestAnimationFrame(() => {
      const heading = document.getElementById(GENERATE_SECTION_TITLE_ID);
      heading?.scrollIntoView?.({ block: "start", behavior: "smooth" });
      heading?.focus?.({ preventScroll: true });
    });
  }, [isMobile, setGenerateOpen]);

  // モバイルタブバーのボタン操作。同じタブを再タップしたら閉じる（トグル）。
  const handleMobileTabClick = useCallback((sheet: "route" | "map" | "settings") => {
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

  // 生成条件のうち重み設定の比較キー（上書き無効時はnull＝バックエンド既定値を表す）
  const currentWeightsKey = JSON.stringify(weightOverrideEnabled ? { scoringWeights, routePreference } : null);

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

        {/* 評価重みパネル（研究インターフェース改善Phase2 §10-1/4）。重みは生成条件
            そのものなので、研究モードON時はこのブロック内へ現れる（§14の分離方針は
            研究モードのトグル自体を開発者向けブロックに置くことで維持）。 */}
        {researchEnabled && (
          <div className={styles.legendCard}>
            <WeightPanel
              overrideEnabled={weightOverrideEnabled}
              onOverrideEnabledChange={setWeightOverrideEnabled}
              scoringWeights={scoringWeights}
              onScoringWeightsChange={setScoringWeights}
              routePreference={routePreference}
              onRoutePreferenceChange={setRoutePreference}
            />
          </div>
        )}

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
            2件以上たまったときだけ表示する。 */}
        {researchEnabled && <ComparisonPanel slots={experimentSlots} />}
      </>
    );
  }

  // 「地図の見え方」の中身。開発者向け機能はrenderSettingsSectionBody（独立した
  // 「設定」ブロック）へ分離済み（一般ユーザーは使わないログ起動を地図上のアイコンから
  // 追い出した際に、「地図の見え方」内の折りたたみからも独立ブロックへ格上げした、T43）。
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
          routeStyleModeId={routeStyleModeId}
          onRouteStyleModeChange={setRouteStyleModeId}
          hiddenRouteLegendKeys={hiddenRouteLegendKeys}
          onRouteLegendToggle={handleRouteLegendToggle}
          hasDetail={hasDetail}
          onGoToGenerate={handleGoToGenerate}
        />
      </div>
    );
  }

  // 「設定」ブロックの中身: ログ・システム状況・研究モード・疎通確認・キャッシュ更新など、
  // 一般ユーザーは触らない開発者向け機能をまとめる。デバッグログの起動ボタンは、デバッグ
  // モード（DebugPanelのチェック）がONのときだけ現れる（以前の地図上trailingButtonと
  // 同じ条件。ログの記録自体がチェックボックス依存のため）。システム状況（commit・起動
  // 日時・外部API呼出サマリ）はデバッグログの記録有無と無関係に確認したい情報のため、
  // 常時表示のボタンにしている。チェックボックスと同じdebugControl内に置いてnowrapに
  // することで、他のsystemRow項目（研究モード等）と並んで縦積みの「メニュー」に見えない
  // ようにしている。アイコンのみのボタンにしているのも、隣に文言を並べる冗長さを避けるため。
  // 起動すると地図に浮かぶ独立したフローティングパネルが開く（T43）。ログ本文（DebugConsole）
  // とシステム状況（SystemStatusPanel）は情報源・更新頻度が異なるため別パネルに分離した
  // （2026-08-16、ユーザーFB「中身が混ざって見にくい」）。
  function renderSettingsSectionBody() {
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
          <ResearchPanel />
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
                    「B. 地図の見え方（表示系・即時反映）」「C. 設定（開発者向け）」の
                    3ブロック構成（UI一貫性再編T30、地図上のログアイコン廃止に伴い開発者向けを
                    Bから独立ブロックへ格上げ、T43）。生成に効く条件（出発地点・距離・重み）が
                    画面のあちこちに分散していた状態を解消し、系統ごとに反映タイミングを揃える。 */}

                {/* A. ルートを作る: アプリの主機能のため最上部・デフォルト開。このブロック内の
                    編集は生成ボタンを押すまで地図へ影響しない。 */}
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

                {/* C. 設定: デバッグログ起動・研究モード・疎通確認・キャッシュ更新など、
                    一般ユーザーは通常触らない機能。デフォルト閉の折りたたみにする（T30・T43）。 */}
                <details className={styles.blockSection}>
                  <summary className={styles.blockSummary}>設定</summary>
                  <div className={styles.blockBody}>{renderSettingsSectionBody()}</div>
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
            showRoad={layerVisibility.road}
            showTrafficStress={layerVisibility.trafficStress}
            showBicycleInfra={layerVisibility.bicycleInfra}
            showDesignation={layerVisibility.designation}
            showStopPoi={layerVisibility.stopPoi}
            showIntersections={layerVisibility.intersections}
            showAccidents={layerVisibility.accidents}
            roadHiddenKeysByMode={debouncedRoadHiddenKeysByMode}
            staticLegendHiddenKeysByAxis={debouncedStaticLegendHiddenKeysByAxis}
            routeLayerOn={layerVisibility.route}
            routeStyleModeId={routeStyleModeId}
            hiddenRouteLegendKeys={hiddenRouteLegendKeys}
            onRegionZoomHintChange={setRegionZoomTooWide}
            refreshToken={refreshToken}
            experimentSlots={researchEnabled ? experimentSlots : []}
          />

          <MapOverlayControls layers={overlayLayers} onToggle={handleLayerToggle} />

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

          {/* デバッグログ・システム状況の起動は「設定」ブロック内のボタン
              （renderSettingsSectionBody）から。position: fixedの独立フローティングパネルの
              ためDOM上の位置は表示に影響しない。 */}
          <DebugConsole open={debugConsoleOpen} onClose={() => setDebugConsoleOpen(false)} />
          <SystemStatusPanel open={systemStatusOpen} onClose={() => setSystemStatusOpen(false)} />
        </div>
      </div>

      {/* モバイル: サイドバーの全面ドロワーだった旧UIを、下部タブバー＋部分シート3枚へ置換
          （モバイル実機フィードバック対応T34、開発者向け機能の独立ブロック化に伴い
          「設定」タブを追加、T43）。「設定」は一般ユーザーが日常的に使う2タブより
          控えめな幅にする（tabButtonSmall）。シート表示中も地図の上側が見えたまま
          パン/ズームできる（暗幕なし、詳細はBottomSheetのコメント参照）。 */}
      {isMobile && (
        <>
          <nav className={styles.mobileTabBar} aria-label="パネル切り替え">
            <button
              type="button"
              aria-pressed={mobileSheet === "route"}
              onClick={() => handleMobileTabClick("route")}
              className={mobileSheet === "route" ? `${styles.tabButton} ${styles.tabButtonActive}` : styles.tabButton}
            >
              ルートを作る
            </button>
            <button
              type="button"
              aria-pressed={mobileSheet === "map"}
              onClick={() => handleMobileTabClick("map")}
              className={mobileSheet === "map" ? `${styles.tabButton} ${styles.tabButtonActive}` : styles.tabButton}
            >
              地図の見え方
            </button>
            <button
              type="button"
              aria-pressed={mobileSheet === "settings"}
              onClick={() => handleMobileTabClick("settings")}
              className={
                mobileSheet === "settings"
                  ? `${styles.tabButton} ${styles.tabButtonSmall} ${styles.tabButtonActive}`
                  : `${styles.tabButton} ${styles.tabButtonSmall}`
              }
            >
              設定
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
            open={mobileSheet === "settings"}
            onClose={() => setMobileSheet(null)}
            title="設定"
            titleId={SETTINGS_SHEET_TITLE_ID}
            heightVh={mobileSheetHeightVh}
            onHeightChange={handleMobileSheetHeightChange}
            onHeightCommit={commitMobileSheetHeight}
          >
            {renderSettingsSectionBody()}
          </BottomSheet>
        </>
      )}
    </div>
  );
}
