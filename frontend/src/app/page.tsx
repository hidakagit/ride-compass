"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapView from "@/components/Map/MapView";
import BackendStatus from "@/components/BackendStatus";
import DebugPanel from "@/components/DebugPanel/DebugPanel";
import ResearchPanel from "@/components/ResearchPanel/ResearchPanel";
import DebugConsole from "@/components/DebugConsole/DebugConsole";
import LocationControl from "@/components/LocationControl/LocationControl";
import MapOverlayControls, { type OverlayLayerChip } from "@/components/MapOverlayControls/MapOverlayControls";
import { LogIcon } from "@/components/Map/icons";
import MapLayersPanel from "@/components/MapLayersPanel/MapLayersPanel";
import BottomSheet, { clampSheetHeightVh, DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import {
  MAP_LAYERS,
  layerSectionDomId,
  type MapLayerId,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import { summarizeLegendFilters } from "@/components/Map/legendFilter";
import { ROAD_FILTER_AXES, type RoadFilterAxisId } from "@/components/Map/roadFilterAxes";
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
import { useIsomorphicLayoutEffect } from "@/hooks/useIsomorphicLayoutEffect";
import { useLocation } from "@/hooks/useLocation";
import { generateRoutes } from "@/services/routeApi";
import { getCurrentWeather } from "@/services/weatherApi";
import type { Coordinates, RouteCandidate, RoutePreferenceWeights, ScoringWeights } from "@/types/route";
import type { WeatherConditions } from "@/types/weather";
import { EXPERIMENT_SLOT_COLORS, MAX_EXPERIMENT_SLOTS, type ExperimentSlot } from "@/types/experimentSlot";
import styles from "./page.module.css";

const DISTANCE_TOLERANCE_KM = 5;

// 道路情報の絞り込みチェックを地図へ反映するまでの猶予。チェック自体は即時反映が原則
// （T31）だが、連続タップのたびにMapLibreのフィルタ再適用を走らせない（useDebouncedValue参照）。
const ROAD_FILTER_DEBOUNCE_MS = 400;

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

function loadStoredStyleMode<T extends string>(storageKey: string, isValid: (v: string | null) => v is T, fallback: T): T {
  try {
    const stored = window.localStorage.getItem(storageKey);
    if (isValid(stored)) return stored;
  } catch {
    // 読み出し不可はデフォルト扱い
  }
  return fallback;
}

function loadStoredJson(key: string): unknown {
  try {
    const raw = window.localStorage.getItem(key);
    return raw == null ? null : JSON.parse(raw);
  } catch {
    // 読み出し不可・壊れたJSONはデフォルト扱い
    return null;
  }
}

function saveStoredJson(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // 保存不可でもこのセッション内の設定は有効
  }
}

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

  // 地図レイヤーのON/OFF（MAP_LAYERSのid単位。レイヤーを追加したらここへ初期値を1つ足す）
  const [layerVisibility, setLayerVisibility] = useState<MapLayerVisibility>({
    elevation: false,
    road: false,
    trafficStress: false,
    bicycleInfra: false,
    route: true,
  });
  const [routeStyleModeId, setRouteStyleModeId] = useState<RouteStyleModeId>(DEFAULT_ROUTE_STYLE_MODE_ID);
  // 凡例タップで非表示にしたカテゴリ（モード別に保持。モードを行き来しても各モードの
  // 取捨選択が残る）。路面モードとルートモードのIDは互いに重複しないため1つのレコードで
  // 両系統を管理できる（localStorageへの保存・復元は下の復元エフェクト参照、T32）。
  const [hiddenLegendKeysByMode, setHiddenLegendKeysByMode] = useState<Record<string, string[]>>({});
  // 「ルートを作る」セクションの開閉（デスクトップのみ。主機能のためデフォルト開。
  // 開閉の保存はT32）。モバイルはBottomSheetの開閉自体がこれに相当するため参照しない
  // （モバイル実機フィードバック対応T34）。
  const [generateOpen, setGenerateOpen] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  // モバイルで開いている下部シート（「ルートを作る」/「地図の見え方」の排他表示、または
  // どちらも閉じたnull＝地図全面表示）。デスクトップでは使わない。
  const [mobileSheet, setMobileSheet] = useState<MobileSheet>(null);
  const [mobileSheetHeightVh, setMobileSheetHeightVh] = useState(DEFAULT_SHEET_HEIGHT_VH);
  const [regionZoomTooWide, setRegionZoomTooWide] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  // デバッグログパネル自体の開閉。デバッグモードON＝ログ記録は常時有効だが、パネル表示は
  // 別（常時画面を占有させたくないという実機フィードバックを受け、右上の起動アイコンで
  // 開閉する方式へ変更、モバイル実機フィードバック対応T42）。デフォルト閉。
  const [debugConsoleOpen, setDebugConsoleOpen] = useState(false);

  const debugEnabled = useDebugEnabled();
  const researchEnabled = useResearchEnabled();

  const selectedCandidate = routes.find((r) => r.id === selectedRouteId) ?? null;
  const hasDetail = !!selectedCandidate?.segments && selectedCandidate.segments.length > 0;

  const isMobile = useIsMobile();

  // 前回の「地図の見え方」設定（色分けモード・レイヤーON/OFF・絞り込みキー）と
  // 「ルートを作る」の開閉（デスクトップ）を復元する。useStateの初期化子でlocalStorageを
  // 読むとSSR（プリレンダー）時のHTMLとハイドレーション結果がずれるため、マウント後に読む。
  // レイアウトエフェクトなのはちらつき防止のため（isMobile自身の判定と同じ理由）。
  useIsomorphicLayoutEffect(() => {
    setRouteStyleModeId(
      loadStoredStyleMode(ROUTE_STYLE_MODE_STORAGE_KEY, isRouteStyleModeId, DEFAULT_ROUTE_STYLE_MODE_ID),
    );

    // レイヤーON/OFF: 既知のレイヤーIDかつboolean値のものだけ採用する（レイヤーの増減や
    // 壊れた保存値があっても、残りの設定は活かして既定値で埋める）
    const storedVisibility = loadStoredJson(LAYER_VISIBILITY_STORAGE_KEY);
    if (typeof storedVisibility === "object" && storedVisibility !== null) {
      setLayerVisibility((prev) => {
        const next = { ...prev };
        for (const id of Object.keys(next) as MapLayerId[]) {
          const value = (storedVisibility as Record<string, unknown>)[id];
          if (typeof value === "boolean") next[id] = value;
        }
        return next;
      });
    }

    // 絞り込み・凡例の非表示キー: 「文字列の配列」の形のエントリだけ採用する
    const storedHidden = loadStoredJson(HIDDEN_LEGEND_KEYS_STORAGE_KEY);
    if (typeof storedHidden === "object" && storedHidden !== null) {
      const entries = Object.entries(storedHidden as Record<string, unknown>).filter(
        (entry): entry is [string, string[]] =>
          Array.isArray(entry[1]) && entry[1].every((key) => typeof key === "string"),
      );
      if (entries.length > 0) setHiddenLegendKeysByMode(Object.fromEntries(entries));
    }

    const storedGenerateOpen = loadStoredJson(GENERATE_OPEN_STORAGE_KEY);
    if (typeof storedGenerateOpen === "boolean") setGenerateOpen(storedGenerateOpen);

    const storedSheetHeight = loadStoredJson(MOBILE_SHEET_HEIGHT_STORAGE_KEY);
    if (typeof storedSheetHeight === "number" && Number.isFinite(storedSheetHeight)) {
      setMobileSheetHeightVh(clampSheetHeightVh(storedSheetHeight));
    }
  }, []);

  const handleRouteStyleModeChange = useCallback((id: RouteStyleModeId) => {
    setRouteStyleModeId(id);
    try {
      window.localStorage.setItem(ROUTE_STYLE_MODE_STORAGE_KEY, id);
    } catch {
      // 保存不可でも選択自体はこのセッション内で有効
    }
  }, []);

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
  const hiddenRouteLegendKeys = hiddenLegendKeysByMode[routeStyleModeId] ?? NO_HIDDEN_LEGEND_KEYS;
  // T32の保存はエフェクトではなく、状態を変えるハンドラ内で更新後の値を明示的に書く
  // （handleRouteStyleModeChangeと同じ流儀）。エフェクトでの保存だと、開発時StrictModeの
  // 再マウントで「復元前の既定値の保存」が復元読み出しへ割り込み、保存済み設定を既定値で
  // 上書きする実害をPlaywright実機確認で観測したため。
  const toggleHiddenLegendKey = useCallback(
    (modeId: string, key: string) => {
      const current = hiddenLegendKeysByMode[modeId] ?? [];
      const nextKeys = current.includes(key) ? current.filter((k) => k !== key) : [...current, key];
      const next = { ...hiddenLegendKeysByMode, [modeId]: nextKeys };
      setHiddenLegendKeysByMode(next);
      saveStoredJson(HIDDEN_LEGEND_KEYS_STORAGE_KEY, next);
    },
    [hiddenLegendKeysByMode],
  );
  // 道路情報の「すべて表示/すべて隠す」一括操作（1軸分の非表示キー全体の置き換え）。
  // 個別チェックはtoggleHiddenLegendKeyをそのまま使う（絞り込みは即時反映、T31。
  // レイヤーの自動ONはMapLayersPanel側が担う）。
  const handleRoadAxisSetHidden = useCallback(
    (axisId: RoadFilterAxisId, hiddenKeys: string[]) => {
      const next = { ...hiddenLegendKeysByMode, [axisId]: hiddenKeys };
      setHiddenLegendKeysByMode(next);
      saveStoredJson(HIDDEN_LEGEND_KEYS_STORAGE_KEY, next);
    },
    [hiddenLegendKeysByMode],
  );
  const handleRouteLegendToggle = useCallback(
    (key: string) => toggleHiddenLegendKey(routeStyleModeId, key),
    [routeStyleModeId, toggleHiddenLegendKey],
  );

  // 地図への反映だけデバウンスする（チェックボックス・条件サマリは即時のroadHiddenKeysByModeを
  // 参照し、MapViewのフィルタ再適用のみ連続タップを1回へまとめる）。
  const debouncedRoadHiddenKeysByMode = useDebouncedValue(roadHiddenKeysByMode, ROAD_FILTER_DEBOUNCE_MS);

  const handleLayerToggle = useCallback(
    (id: MapLayerId, on: boolean) => {
      const next = { ...layerVisibility, [id]: on };
      setLayerVisibility(next);
      saveStoredJson(LAYER_VISIBILITY_STORAGE_KEY, next);
    },
    [layerVisibility],
  );

  // 「ルートを作る」の開閉もT32の保存対象（ハンドラ内で保存する理由は上のコメント参照）
  const handleGenerateOpenChange = useCallback((open: boolean) => {
    setGenerateOpen(open);
    saveStoredJson(GENERATE_OPEN_STORAGE_KEY, open);
  }, []);

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
  // ルートは色分けモード自体が「何の条件で色分け中か」の情報なので常に出す
  const routeSummary = hasDetail
    ? `色分け: ${getRouteStyleMode(routeStyleModeId).label}${hiddenRouteLegendKeys.length > 0 ? "・一部非表示" : ""}`
    : null;

  // 地図上のチップ行はレイヤーカタログ（MAP_LAYERS）から組み立てる。レイヤーを追加したら
  // summaryの対応をここへ1行足すだけでよい（チップ・サマリ行の描画は汎用）。
  const overlayLayers = useMemo<OverlayLayerChip[]>(
    () =>
      MAP_LAYERS.map((layer) => {
        const disabled = layer.id === "route" && !hasDetail;
        const summary = layer.id === "road" ? roadSummary : layer.id === "route" ? routeSummary : null;
        return {
          id: layer.id,
          label: layer.label,
          on: layerVisibility[layer.id],
          disabled,
          title: disabled ? "ルートを生成・選択すると使えます" : `${layer.description}（設定はサイドバー）`,
          summary,
        };
      }),
    [hasDetail, layerVisibility, roadSummary, routeSummary],
  );

  // 地図上の条件サマリのタップで、「地図の見え方」設定（デスクトップはサイドバー、
  // モバイルは下部シート）を開いて該当レイヤーの設定セクションへ誘導する。閉じていると
  // 中身が未マウントのため、開いた後の再レンダーを待ってから（次フレームで）
  // 対象セクションを展開・スクロール・フォーカスする。
  const handleLayerSummaryClick = useCallback(
    (id: MapLayerId) => {
      if (isMobile) {
        setMobileSheet("map");
      } else {
        setSidebarCollapsed(false);
      }
      requestAnimationFrame(() => {
        const sectionId = layerSectionDomId(id);
        const section = document.getElementById(sectionId);
        // レイヤーごとの設定は折りたたみ（<details>、モバイル実機フィードバック対応T38）の
        // ためデフォルト閉。誘導先が閉じたままではスクロールしても中身が見えないため開く。
        if (section instanceof HTMLDetailsElement) section.open = true;
        const heading = document.getElementById(`${sectionId}-title`);
        heading?.scrollIntoView?.({ block: "start", behavior: "smooth" });
        heading?.focus?.({ preventScroll: true });
      });
    },
    [isMobile],
  );

  // 「地図の見え方」内のルート未生成案内から「ルートを作る」へ誘導する。デスクトップは
  // 該当ブロックを開き、モバイルは「ルートを作る」シートを開く。開いた後の再レンダーを
  // 待ってから（次フレームで）スクロール・フォーカスする（handleLayerSummaryClickと同じ手法）。
  const handleGoToGenerate = useCallback(() => {
    if (isMobile) {
      setMobileSheet("route");
    } else {
      handleGenerateOpenChange(true);
    }
    requestAnimationFrame(() => {
      const heading = document.getElementById(GENERATE_SECTION_TITLE_ID);
      heading?.scrollIntoView?.({ block: "start", behavior: "smooth" });
      heading?.focus?.({ preventScroll: true });
    });
  }, [isMobile, handleGenerateOpenChange]);

  // モバイルタブバーのボタン操作。同じタブを再タップしたら閉じる（トグル）。
  const handleMobileTabClick = useCallback((sheet: "route" | "map" | "settings") => {
    setMobileSheet((prev) => (prev === sheet ? null : sheet));
  }, []);

  // 下部シートの高さ変更。ドラッグ中/キー操作中は見た目の即時反映のみ（onHeightChange）、
  // 確定時のみ保存する（onHeightCommit。ドラッグ中の毎フレーム書き込みを避けるため、
  // T32の他設定と異なりハンドラを分けている）。
  const handleMobileSheetHeightChange = useCallback((vh: number) => {
    setMobileSheetHeightVh(vh);
  }, []);
  const handleMobileSheetHeightCommit = useCallback((vh: number) => {
    saveStoredJson(MOBILE_SHEET_HEIGHT_STORAGE_KEY, vh);
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
          regionZoomTooWide={regionZoomTooWide}
          routeStyleModeId={routeStyleModeId}
          onRouteStyleModeChange={handleRouteStyleModeChange}
          hiddenRouteLegendKeys={hiddenRouteLegendKeys}
          onRouteLegendToggle={handleRouteLegendToggle}
          hasDetail={hasDetail}
          onGoToGenerate={handleGoToGenerate}
        />
      </div>
    );
  }

  // 「設定」ブロックの中身: ログ・研究モード・疎通確認・キャッシュ更新など、一般ユーザーは
  // 触らない開発者向け機能をまとめる。デバッグログの起動ボタンは、デバッグモード
  // （DebugPanelのチェック）がONのときだけ現れる（以前の地図上trailingButtonと同じ条件）。
  // 起動すると地図に浮かぶ独立したフローティングパネル（DebugConsole）が開く（T43）。
  function renderSettingsSectionBody() {
    return (
      <>
        <div className={styles.systemRow}>
          <DebugPanel />
          {debugEnabled && (
            <button
              type="button"
              onClick={() => setDebugConsoleOpen((v) => !v)}
              aria-pressed={debugConsoleOpen}
              className={styles.logToggleButton}
            >
              <LogIcon size={14} />
              {debugConsoleOpen ? "デバッグログを隠す" : "デバッグログを表示"}
            </button>
          )}
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
                  onToggle={(e) => handleGenerateOpenChange(e.currentTarget.open)}
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
            roadHiddenKeysByMode={debouncedRoadHiddenKeysByMode}
            routeLayerOn={layerVisibility.route}
            routeStyleModeId={routeStyleModeId}
            hiddenRouteLegendKeys={hiddenRouteLegendKeys}
            onRegionZoomHintChange={setRegionZoomTooWide}
            refreshToken={refreshToken}
            experimentSlots={researchEnabled ? experimentSlots : []}
          />

          <MapOverlayControls layers={overlayLayers} onToggle={handleLayerToggle} onSummaryClick={handleLayerSummaryClick} />

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

          {/* デバッグログの起動は「設定」ブロック内のボタン（renderSettingsSectionBody）から。
              position: fixedの独立フローティングパネルのためDOM上の位置は表示に影響しない。 */}
          <DebugConsole open={debugConsoleOpen} onClose={() => setDebugConsoleOpen(false)} />
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
            onHeightCommit={handleMobileSheetHeightCommit}
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
            onHeightCommit={handleMobileSheetHeightCommit}
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
            onHeightCommit={handleMobileSheetHeightCommit}
          >
            {renderSettingsSectionBody()}
          </BottomSheet>
        </>
      )}
    </div>
  );
}
