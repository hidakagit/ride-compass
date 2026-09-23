"use client";

/** 地図の見え方（どのレイヤーを出すか・レンズ・凡例で隠した行）の状態と、そこから導く
 * 地図への値・操作部品への値。
 *
 * 画面の残りから受け取るのは、軸やレイヤーの種類を知らない値だけ（軸カタログ・ルートの
 * 文脈・走行条件・評価の重みと軸の色）。軸・レイヤー・気象の要素を足しても、この入力は
 * 変わらない。
 *
 * 出発時刻は例外的に**ここから出る**。出発時刻の状態は動的気象レイヤーのフック
 * （`useDynamicWeatherLayers`）が持ち、そのフックはレイヤーのON/OFF・災害の要素トグル・
 * 表示範囲という見え方の状態を入力に取るため、見え方を持つこのフックの中でしか呼べない。
 */
import { useCallback, useMemo, useState, type ComponentProps } from "react";

import type LensControl from "@/components/LensControl/LensControl";
import type { MapViewProps } from "@/components/Map/MapView";
import type MapOverlayControls from "@/components/MapOverlayControls/MapOverlayControls";
import {
  buildDefaultLayerVisibility,
  buildMapLayers,
  tileVersionGatedLayerIds,
  type LayerDataStatusByLayer,
  type MapLayerId,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import { DEFAULT_ROUTE_STYLE_MODE_ID, type LensId } from "@/components/Map/routeStyleModes";
import type { MapViewport } from "@/components/Map/windLayer";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useDedicatedWayValues } from "@/hooks/useDedicatedWayValues";
import { useDynamicWeatherLayers } from "@/hooks/useDynamicWeatherLayers";
import { useStoredBooleanState, useStoredState } from "@/hooks/useStoredState";
import { useTileVersionsReady } from "@/hooks/useTileVersionsReady";
import type { AxisCatalog } from "@/lib/axisCatalog";

import {
  dedicatedResultsForMap,
  lensAxisVisibility,
  lensBackgroundShown,
  lensDataStatus,
  lensDedicatedWayValueVisibility,
  lensFetchAxes,
  lensLegend,
  lensOptions,
  restoreLens,
} from "./lens";
import {
  deserializeHiddenLegendKeys,
  EMPTY_HIDDEN_LEGEND_KEYS,
  hiddenKeysOf,
  mapHiddenKeysFrom,
  presentHiddenKeys,
  serializeHiddenLegendKeys,
  toggleHiddenKey,
  withHiddenKeys,
} from "./legendFilters";
import {
  deserializeLayerVisibility,
  DISASTER_LAYER_ID,
  disasterLegendAxes,
  hasVisibleLegendFilter,
  layerVisibilityChanged,
  overlayChips,
  secondaryAxisCasingLayerIds,
  serializeLayerVisibility,
  versionMissingStatus,
  type ScreenLegendAxis,
} from "./overlayChips";

const LENS_STORAGE_KEY = "ridecompass:route-style-mode";
const LENS_KEEP_AFTER_ROUTE_STORAGE_KEY = "ridecompass:lens-keep-after-route";
const LAYER_VISIBILITY_STORAGE_KEY = "ridecompass:layer-visibility";
const HIDDEN_LEGEND_KEYS_STORAGE_KEY = "ridecompass:hidden-legend-keys";

/** 凡例のチェックを地図の絞り込みへ反映するまでの遅れ。連続で何行も外す操作を、タイル全体の
 * 描き直し1回へまとめる（チェックの見た目は即座に変わる）。 */
const LEGEND_FILTER_DEBOUNCE_MS = 400;

const DEFAULT_LAYER_VISIBILITY = buildDefaultLayerVisibility();

/** `MapView`のpropsのうち、地図の見え方に属するもの。`MapView`はこれを1つのpropで受け取る想定。 */
export type MapLook = Required<
  Pick<
    MapViewProps,
    | "staticLayerVisibility"
    | "routeLayerOn"
    | "dynamicWeather"
    | "rampAxes"
    | "axisVisibility"
    | "secondaryAxisCasingLayerIds"
    | "dedicatedAxes"
    | "dedicatedWayValueVisibility"
    | "dedicatedWayValues"
    | "dedicatedWayValueLoading"
    | "dedicatedWayValueHiddenBands"
    | "rideConditions"
    | "roadHiddenKeysByMode"
    | "staticLegendHiddenKeysByAxis"
    | "routeStyleModes"
    | "routeStyleModeId"
    | "hiddenRouteLegendKeys"
    | "tileVersionsReady"
    | "onTileZoomTooWideChange"
    | "onViewportChange"
    | "onLayerDataStatusChange"
  >
>;

export interface MapViewInputs {
  /** `useAxisCatalog()`の値。 */
  catalog: AxisCatalog;
  route: {
    /** 候補が1件以上あるか。 */
    hasRoutes: boolean;
    /** 選択中の候補の区間まで確定しているか（ルート確定後）。 */
    hasDetail: boolean;
  };
  /** 走行条件のうち、出発時刻を除くもの（出発時刻はこのフックが返す`departure`が持つ）。 */
  ride: {
    travelBearingDeg: number;
    assumedSpeedKmh: number;
  };
  /** いまの評価の設定の重み（軸id→重み）。重み0の軸をレンズの一覧で「未使用」と示すのに使う。 */
  axisWeights: Readonly<Record<string, number>>;
  /** 軸id→色（ルート結果と同じ配色）。レンズの一覧の色に使う。 */
  axisColors: Readonly<Record<string, string>>;
}

export interface MapViewControls {
  lens: ComponentProps<typeof LensControl>;
  overlay: ComponentProps<typeof MapOverlayControls>;
  /** 地図下部の「まとめて元に戻す」。レイヤーのON/OFFと凡例の絞り込みは別の状態なので別々に戻す。 */
  reset: {
    /** 既定と違うレイヤーが1つでもあるか。 */
    layersChanged: boolean;
    resetLayers: () => void;
    /** いま描いている凡例のどこかで行を隠しているか。 */
    legendFiltered: boolean;
    clearLegendFilters: () => void;
  };
}

export interface MapViewState {
  look: MapLook;
  controls: MapViewControls;
  /** いまのレンズ。生成リクエストの`lens_axis_id`はここから作る。 */
  lens: LensId;
  /** 出発時刻（動的気象レイヤーと専用配信軸が共有する時刻）。条件バーと生成リクエストが読む。 */
  departure: {
    at: Date;
    /** 利用者が選んだ時刻か。falseの間は「今」へ追従して進む。 */
    pinned: boolean;
    setAt: (time: Date) => void;
    /** 「今」への追従へ戻す。 */
    followNow: () => void;
  };
}

export function useMapView({ catalog, route, ride, axisWeights, axisColors }: MapViewInputs): MapViewState {
  const [layerVisibility, setLayerVisibility] = useStoredState<MapLayerVisibility>(
    LAYER_VISIBILITY_STORAGE_KEY,
    DEFAULT_LAYER_VISIBILITY,
    { serialize: serializeLayerVisibility, deserialize: deserializeLayerVisibility, reloadKey: catalog.loaded },
  );
  // 選べるモードはカタログが届いて初めて軸を含むため、届いた時点で読み直す。
  const [lens, setLens] = useStoredState<LensId>(LENS_STORAGE_KEY, DEFAULT_ROUTE_STYLE_MODE_ID, {
    serialize: (value) => value,
    deserialize: (raw) => restoreLens(raw, catalog.routeStyleModes),
    reloadKey: catalog.loaded,
  });
  const [keepAfterRoute, setKeepAfterRoute] = useStoredBooleanState(LENS_KEEP_AFTER_ROUTE_STORAGE_KEY, true);
  const [hidden, setHidden] = useStoredState(HIDDEN_LEGEND_KEYS_STORAGE_KEY, EMPTY_HIDDEN_LEGEND_KEYS, {
    serialize: serializeHiddenLegendKeys,
    deserialize: deserializeHiddenLegendKeys,
  });
  const [viewport, setViewport] = useState<MapViewport | null>(null);
  const [mapLayerStatus, setMapLayerStatus] = useState<LayerDataStatusByLayer>({});
  const [zoomTooWideLayerIds, setZoomTooWideLayerIds] = useState<readonly MapLayerId[]>([]);
  const tileVersionsReady = useTileVersionsReady();

  const weather = useDynamicWeatherLayers({
    visibility: layerVisibility,
    hiddenDisasterSources: hiddenKeysOf(hidden, DISASTER_LAYER_ID),
    mapViewport: viewport,
  });

  const { rampAxes, dedicatedAxes, routeStyleModes } = catalog;
  const backgroundShown = lensBackgroundShown(route.hasDetail, keepAfterRoute);
  const fetchAxes = useMemo(
    () => lensFetchAxes(dedicatedAxes, lens, backgroundShown),
    [dedicatedAxes, lens, backgroundShown],
  );
  const dedicatedResults = useDedicatedWayValues(
    fetchAxes,
    viewport,
    ride.travelBearingDeg,
    weather.dynamicLayerTargetTime,
    ride.assumedSpeedKmh,
  );

  const axisVisibility = useMemo(
    () => lensAxisVisibility(rampAxes, lens, backgroundShown),
    [rampAxes, lens, backgroundShown],
  );
  const dedicatedWayValueVisibility = useMemo(
    () => lensDedicatedWayValueVisibility(dedicatedAxes, lens, backgroundShown),
    [dedicatedAxes, lens, backgroundShown],
  );
  const { dedicatedWayValues, dedicatedWayValueLoading } = useMemo(
    () => dedicatedResultsForMap(dedicatedResults),
    [dedicatedResults],
  );

  const debouncedHidden = useDebouncedValue(hidden, LEGEND_FILTER_DEBOUNCE_MS);
  const liveMapHidden = useMemo(
    () => mapHiddenKeysFrom(hidden, rampAxes, dedicatedAxes),
    [hidden, rampAxes, dedicatedAxes],
  );
  const debouncedMapHidden = useMemo(
    () => mapHiddenKeysFrom(debouncedHidden, rampAxes, dedicatedAxes),
    [debouncedHidden, rampAxes, dedicatedAxes],
  );
  const lensHiddenKeys = hiddenKeysOf(hidden, lens);

  const secondaryCasing = useMemo(
    () => secondaryAxisCasingLayerIds(catalog.secondaryAxes, layerVisibility),
    [catalog.secondaryAxes, layerVisibility],
  );
  const rideConditions = useMemo(
    () => ({ bearingDeg: ride.travelBearingDeg, at: weather.dynamicLayerTargetTime, speedKmh: ride.assumedSpeedKmh }),
    [ride.travelBearingDeg, weather.dynamicLayerTargetTime, ride.assumedSpeedKmh],
  );

  const legend = useMemo(
    () => lensLegend({ lens, hasDetail: route.hasDetail, routeStyleModes, rampAxes, dedicatedAxes }),
    [lens, route.hasDetail, routeStyleModes, rampAxes, dedicatedAxes],
  );
  const axisOptions = useMemo(
    () =>
      lensOptions({
        axes: catalog.axes,
        rampAxes,
        dedicatedAxes,
        axisWeights,
        defaultWeights: catalog.defaultWeights,
        axisColors,
      }),
    [catalog.axes, rampAxes, dedicatedAxes, axisWeights, catalog.defaultWeights, axisColors],
  );
  const lensLegendHiddenKeys = presentHiddenKeys(legend, lensHiddenKeys);

  const layers = useMemo(
    () => buildMapLayers(rampAxes, dedicatedAxes, catalog.accidentYears),
    [rampAxes, dedicatedAxes, catalog.accidentYears],
  );
  const versionMissingLayerIds = useMemo(
    () => (tileVersionsReady ? [] : tileVersionGatedLayerIds(rampAxes)),
    [tileVersionsReady, rampAxes],
  );
  const catalogSettled = catalog.loaded || catalog.failed;
  const dataStatus = useMemo(
    () => ({
      ...mapLayerStatus,
      ...weather.dynamicWeatherDataStatus,
      ...versionMissingStatus(versionMissingLayerIds, catalogSettled),
    }),
    [mapLayerStatus, weather.dynamicWeatherDataStatus, versionMissingLayerIds, catalogSettled],
  );
  const screenLegends = useMemo(() => {
    // ルートにひもづくレイヤー（記述子の`kind: "dynamic"`）の凡例は、選択中の候補を塗っている
    // レンズのモードの凡例。保存先はレンズと同じなので、どちらで隠しても同じ段が隠れる。
    const routeLegend: readonly ScreenLegendAxis[] =
      route.hasDetail && legend.length > 0 ? [{ label: "", legend, axisId: lens }] : [];
    const legends: Partial<Record<MapLayerId, readonly ScreenLegendAxis[]>> = {
      [DISASTER_LAYER_ID]: disasterLegendAxes(),
    };
    for (const layer of layers) if (layer.kind === "dynamic") legends[layer.id] = routeLegend;
    return legends;
  }, [route.hasDetail, legend, lens, layers]);
  const chips = useMemo(
    () =>
      overlayChips({
        layers,
        visibility: layerVisibility,
        dataStatus,
        versionMissingLayerIds,
        zoomTooWideLayerIds,
        hidden,
        screenLegends,
        hasRoutes: route.hasRoutes,
      }),
    [
      layers,
      layerVisibility,
      dataStatus,
      versionMissingLayerIds,
      zoomTooWideLayerIds,
      hidden,
      screenLegends,
      route.hasRoutes,
    ],
  );

  const onToggleLayer = useCallback(
    (id: MapLayerId, on: boolean) => setLayerVisibility((prev) => ({ ...prev, [id]: on })),
    [setLayerVisibility],
  );
  const onToggleLegendEntry = useCallback(
    (axisId: string, key: string) => setHidden((prev) => toggleHiddenKey(prev, axisId, key)),
    [setHidden],
  );
  const onSetLegendAxisHidden = useCallback(
    (axisId: string, keys: readonly string[]) => setHidden((prev) => withHiddenKeys(prev, axisId, keys)),
    [setHidden],
  );
  const resetLayers = useCallback(() => setLayerVisibility(buildDefaultLayerVisibility()), [setLayerVisibility]);
  const clearLegendFilters = useCallback(() => setHidden(EMPTY_HIDDEN_LEGEND_KEYS), [setHidden]);

  return {
    look: {
      staticLayerVisibility: layerVisibility,
      routeLayerOn: layerVisibility.route === true,
      dynamicWeather: weather.dynamicWeather,
      rampAxes,
      axisVisibility,
      secondaryAxisCasingLayerIds: secondaryCasing,
      dedicatedAxes,
      dedicatedWayValueVisibility,
      dedicatedWayValues,
      dedicatedWayValueLoading,
      dedicatedWayValueHiddenBands: liveMapHidden.dedicatedWayValueHiddenBands,
      rideConditions,
      roadHiddenKeysByMode: debouncedMapHidden.roadHiddenKeysByMode,
      staticLegendHiddenKeysByAxis: debouncedMapHidden.staticLegendHiddenKeysByAxis,
      routeStyleModes,
      routeStyleModeId: lens,
      hiddenRouteLegendKeys: lensHiddenKeys,
      tileVersionsReady,
      onTileZoomTooWideChange: setZoomTooWideLayerIds,
      onViewportChange: setViewport,
      onLayerDataStatusChange: setMapLayerStatus,
    },
    controls: {
      lens: {
        lens,
        onLensChange: setLens,
        axisOptions,
        legend,
        hiddenLegendKeys: lensLegendHiddenKeys,
        onToggleLegendKey: (key) => onToggleLegendEntry(lens, key),
        onSetHiddenLegendKeys: (keys) => onSetLegendAxisHidden(lens, keys),
        keepAfterRoute,
        onKeepAfterRouteChange: setKeepAfterRoute,
        hasDetail: route.hasDetail,
        dataStatus: lensDataStatus(dedicatedResults.get(lens)),
      },
      overlay: {
        layers: chips,
        onToggle: onToggleLayer,
        onLegendEntryToggle: onToggleLegendEntry,
        onLegendAxisSetHidden: onSetLegendAxisHidden,
      },
      reset: {
        layersChanged: layerVisibilityChanged(layerVisibility),
        resetLayers,
        legendFiltered: hasVisibleLegendFilter(chips, lensLegendHiddenKeys),
        clearLegendFilters,
      },
    },
    lens,
    departure: {
      at: weather.dynamicLayerTargetTime,
      pinned: weather.departureTimePinned,
      setAt: weather.setDynamicLayerTargetTime,
      followNow: weather.handleDynamicLayerNow,
    },
  };
}
