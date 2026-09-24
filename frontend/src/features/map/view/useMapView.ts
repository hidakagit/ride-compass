"use client";

/** 地図の見え方（どのレイヤーを出すか・レンズ・凡例で隠した行）の状態と、そこから導く
 * 地図への値・操作部品への値。
 *
 * 画面から受け取るのはルートの文脈・走行条件・生成に使われた重みだけで、軸やレイヤーの種類を
 * 知らない。軸カタログとタイル世代は共有の源泉から読む。
 */
import { useMemo, useState, type ComponentProps } from "react";

import type LensControl from "@/features/map/LensControl/LensControl";
import {
  buildDefaultLayerVisibility,
  buildMapLayers,
  deriveFetchLayerStatus,
  tileVersionGatedLayerIds,
  tileZoomTooWideLayerIds,
  type LayerDataStatusByLayer,
  type MapLayerVisibility,
} from "@/features/map/layers/mapLayers";
import type { LensId } from "@/lib/mapDisplay/routeStyleModes";
import type { MapViewport } from "@/features/map/layers/windLayer";
import type MapOverlayControls from "@/features/map/MapOverlayControls/MapOverlayControls";
import { mapDisplay } from "@/types/generated/mapDisplay";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useDedicatedWayValues } from "@/features/map/useDedicatedWayValues";
import { useDynamicWeatherLayers } from "@/features/map/useDynamicWeatherLayers";
import { useStoredBooleanState, useStoredState } from "@/hooks/useStoredState";
import { useTileVersionsReady } from "@/features/map/useTileVersionsReady";

import {
  deserializeHiddenLegendKeys,
  hiddenKeysOf,
  presentHiddenKeys,
  toggleHiddenKey,
  withHiddenKeys,
} from "./legendFilters";
import { DEFAULT_ROUTE_STYLE_MODE_ID, isRouteStyleModeId, lensLegend, lensOptions, paintedAxisId } from "./lens";
import type { HiddenLegendKeys, MapLook } from "./mapLook";
import { deserializeLayerVisibility, overlayChips } from "./overlayChips";

/** 凡例のチェックを地図の絞り込みへ反映するまでの遅れ。連続で何行も外す操作を、描き直し
 * 1回へまとめる（チェックの見た目は即座に変わる）。 */
const LEGEND_FILTER_DEBOUNCE_MS = 400;

const ROUTE_LAYER_ID = "route";
const NO_HIDDEN: HiddenLegendKeys = {};

interface MapViewInputs {
  /** 候補を選んでいるか。 */
  hasSelectedRoute: boolean;
  /** 選択中の候補の区間まで確定しているか（ルート確定後）。 */
  hasDetail: boolean;
  /** 走行条件。専用配信軸の値と気象レイヤーの表示時刻がこれに従う。 */
  ride: { bearingDeg: number; at: Date; speedKmh: number };
  /** 刻みへ丸めた現在時刻（`useDepartureTime`）。 */
  now: Date;
  /** 生成に実際に使われた重み。生成前はnull。 */
  usedWeights: Readonly<Record<string, number>> | null;
}

interface MapViewState {
  look: MapLook;
  lensControl: ComponentProps<typeof LensControl>;
  overlayControls: ComponentProps<typeof MapOverlayControls>;
  /** 地図下部の、まとめて操作するボタン。 */
  bulk: {
    anyLayerOn: boolean;
    hideAllLayers: () => void;
    anyLegendHidden: boolean;
    showAllLegendRows: () => void;
    redraw: () => void;
  };
  /** いまのレンズ。生成リクエストの`lens_axis_id`はここから作る。 */
  lens: LensId;
}

export function useMapView({ hasSelectedRoute, hasDetail, ride, now, usedWeights }: MapViewInputs): MapViewState {
  const catalog = useAxisCatalog();
  const tileVersionsReady = useTileVersionsReady();
  const [layerVisibility, setLayerVisibility] = useStoredState<MapLayerVisibility>(
    "ridecompass:layer-visibility",
    buildDefaultLayerVisibility(),
    { serialize: JSON.stringify, deserialize: deserializeLayerVisibility },
  );
  // 軸を指す保存値はカタログが届いて初めて読めるため、届いた時点で読み直す。
  const [lens, setLens] = useStoredState<LensId>("ridecompass:route-style-mode", DEFAULT_ROUTE_STYLE_MODE_ID, {
    serialize: (value) => value,
    deserialize: (raw) => (isRouteStyleModeId(catalog.routeStyleModes, raw) ? raw : null),
    reloadKey: catalog.loaded,
  });
  const [keepAfterRoute, setKeepAfterRoute] = useStoredBooleanState("ridecompass:lens-keep-after-route", true);
  const [hidden, setHidden] = useStoredState<HiddenLegendKeys>("ridecompass:hidden-legend-keys", NO_HIDDEN, {
    serialize: JSON.stringify,
    deserialize: deserializeHiddenLegendKeys,
  });
  const [viewport, setViewport] = useState<MapViewport | null>(null);
  const [mapLayerStatus, setMapLayerStatus] = useState<LayerDataStatusByLayer>({});
  const [refreshToken, setRefreshToken] = useState(0);

  // チップ配下の名前付きソースの表示切替は、チップidを凡例の保存先の鍵にする（`scene/legends.ts`）。
  const hiddenWeatherSources = useMemo(
    () => Object.fromEntries(mapDisplay.weatherLayerGroups.map((group) => [group, hiddenKeysOf(hidden, group)])),
    [hidden],
  );
  const weather = useDynamicWeatherLayers({
    visibility: layerVisibility,
    hiddenSources: hiddenWeatherSources,
    mapViewport: viewport,
    at: ride.at,
    now,
  });
  const painted = paintedAxisId(lens, hasDetail, keepAfterRoute);
  const fetchAxes = useMemo(
    () => catalog.dedicatedAxes.filter((axis) => axis.axisId === painted),
    [catalog.dedicatedAxes, painted],
  );
  const dedicatedWayValues = useDedicatedWayValues(fetchAxes, viewport, ride.bearingDeg, ride.at, ride.speedKmh);
  const debouncedHidden = useDebouncedValue(hidden, LEGEND_FILTER_DEBOUNCE_MS);

  // MapViewはこの参照が変わるたびに地図の中身を組み直すため、中身が変わったときだけ作る。
  const look = useMemo<MapLook>(
    () => ({
      layerVisibility,
      dynamicWeather: weather.dynamicWeather,
      lens,
      paintedAxisId: painted,
      dedicatedWayValues,
      hiddenLegendKeys: debouncedHidden,
      refreshToken,
      onViewportChange: setViewport,
      onLayerDataStatusChange: setMapLayerStatus,
    }),
    [layerVisibility, weather.dynamicWeather, lens, painted, dedicatedWayValues, debouncedHidden, refreshToken],
  );

  const legend = lensLegend(lens, hasDetail, catalog);
  const lensHidden = presentHiddenKeys(legend, hiddenKeysOf(hidden, lens));
  const lensFetch = dedicatedWayValues.get(lens);
  const chips = overlayChips({
    layers: buildMapLayers(catalog.rampAxes, catalog.dedicatedAxes, catalog.accidentYears),
    visibility: layerVisibility,
    hidden,
    // ルート線の凡例はレンズと同じ保存先なので、どちらで隠しても同じ段が隠れる。
    screenLegends: { [ROUTE_LAYER_ID]: hasDetail ? [{ label: "", legend, axisId: lens }] : [] },
    dataStatus: { ...mapLayerStatus, ...weather.dynamicWeatherDataStatus },
    zoomTooWideLayerIds: viewport ? tileZoomTooWideLayerIds(viewport.zoom) : [],
    versionMissingLayerIds: tileVersionsReady ? [] : tileVersionGatedLayerIds(catalog.rampAxes),
    catalogSettled: catalog.loaded || catalog.failed,
    hasSelectedRoute,
  });
  const setHiddenFor = (axisId: string, keys: readonly string[]) =>
    setHidden((prev) => withHiddenKeys(prev, axisId, keys));
  const toggleHiddenFor = (axisId: string, key: string) => setHidden((prev) => toggleHiddenKey(prev, axisId, key));

  return {
    look,
    lensControl: {
      lens,
      // 選んだ色分けが見えるように、ルートのレイヤーがOFFならONにする。
      onLensChange: (id) => {
        setLens(id);
        setLayerVisibility((prev) => (prev[ROUTE_LAYER_ID] ? prev : { ...prev, [ROUTE_LAYER_ID]: true }));
      },
      axisOptions: lensOptions(
        catalog.axes,
        new Set([...catalog.rampAxes, ...catalog.dedicatedAxes].map((axis) => axis.axisId)),
        usedWeights,
        catalog.axisColors,
      ),
      legend,
      hiddenLegendKeys: lensHidden,
      onToggleLegendKey: (key) => toggleHiddenFor(lens, key),
      onSetHiddenLegendKeys: (keys) => setHiddenFor(lens, keys),
      keepAfterRoute,
      onKeepAfterRouteChange: setKeepAfterRoute,
      hasDetail,
      dataStatus: lensFetch
        ? deriveFetchLayerStatus(
            lensFetch.loading,
            lensFetch.error ? "fetch-failed" : null,
            lensFetch.values.size > 0,
            lensFetch.hasFetched,
          )
        : undefined,
    },
    overlayControls: {
      layers: chips,
      onToggle: (id, on) => setLayerVisibility((prev) => ({ ...prev, [id]: on })),
      onLegendEntryToggle: toggleHiddenFor,
      onLegendAxisSetHidden: setHiddenFor,
    },
    bulk: {
      anyLayerOn: chips.some((chip) => chip.on),
      hideAllLayers: () =>
        setLayerVisibility(
          (prev) => Object.fromEntries(Object.keys(prev).map((id) => [id, false])) as MapLayerVisibility,
        ),
      anyLegendHidden:
        lensHidden.length > 0 ||
        chips.some((chip) => (chip.legendDetails ?? []).some((axis) => axis.hiddenKeys.length > 0)),
      showAllLegendRows: () => setHidden(NO_HIDDEN),
      redraw: () => setRefreshToken((token) => token + 1),
    },
    lens,
  };
}
