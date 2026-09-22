// @vitest-environment node
/** 画面の状態を地図へ伝えたとき、**最後にどうなっているか**。
 *
 * 筋書きは[遷移表](../../../../docs/records/tasks/T1001.md)から取っている。入口は
 * `redrawAllLayers`——「いまの状態から地図を作り直す」1本で、面・路面の線・点データ・
 * 軸レイヤー・動的気象のすべてがここを通る。**新実装ができたら、この束ね方だけを
 * 差し替える**（期待値の側は動かさない）。
 */
import { beforeEach, describe, expect, it } from "vitest";

import { setTileVersions } from "@/services/regionApi";
import { createRecordingMap } from "@/testing/mapTrace/recordingMap";
import { catalogAxis } from "@/components/Map/__fixtures__/catalogAxes";
import { buildMapLayers } from "@/components/Map/mapLayers";
import { buildStaticFilterAxes } from "@/components/Map/staticAttributeLayers";
import { dedicatedWayValueAxesFromCatalogAxes, rampAxesFromCatalogAxes } from "@/components/Map/axisLayers";
import {
  ROAD_MATERIAL_TRACK_LAYER_IDS,
  ROAD_TILE_LAYER_ID,
  ROAD_TILE_SOURCE_ID,
  ROAD_TYPE_LAYER_ID,
  applyAxisFeatureStateValues,
  buildAxisOverlayLayers,
  buildStaticOverlayLayers,
  clearRoadTileFeatureState,
  redrawAllLayers,
  shouldClearDedicatedWayValueFeatureState,
  type RedrawAllLayersProps,
} from "@/components/Map/MapView";

const RAMP_AXES = rampAxesFromCatalogAxes([
  catalogAxis({ axis_id: "ramp", display: { tile_inputs: [{ property: "v", weight: 1 }], thresholds: [50] } }),
]);
const DEDICATED_AXES = dedicatedWayValueAxesFromCatalogAxes([
  catalogAxis({ axis_id: "ded1", dedicated_way_value_layer: true }),
  catalogAxis({ axis_id: "ded2", dedicated_way_value_layer: true }),
]);
const CATALOG = buildMapLayers(RAMP_AXES, DEDICATED_AXES);

function overlayLayers() {
  return buildStaticOverlayLayers(CATALOG, buildAxisOverlayLayers(RAMP_AXES, new Set()), DEDICATED_AXES);
}

/** 何も出していない状態。個々のテストは必要な分だけ上書きする。 */
function baseState(): RedrawAllLayersProps {
  return {
    routes: [],
    selectedRouteId: null,
    routeLayerOn: false,
    routeStyleModes: [],
    routeStyleModeId: "none",
    hiddenRouteLegendKeys: [],
    spliceStretches: [],
    splicedRoute: null,
    staticLayerVisibility: {},
    dynamicWeather: {},
    dedicatedWayValueVisibility: {},
    axisVisibility: {},
    roadHiddenKeysByMode: {},
    staticLegendHiddenKeysByAxis: {},
    experimentSlots: [],
    dedicatedWayValues: new Map(),
    staticOverlayLayers: overlayLayers(),
    staticFilterAxes: buildStaticFilterAxes(RAMP_AXES),
    inspectedWayId: null,
  } as unknown as RedrawAllLayersProps;
}

function layerIdOf(key: string): string {
  const entry = overlayLayers().find((layer) => layer.key === key);
  if (!entry) throw new Error(`レイヤーカタログに ${key} が無い`);
  return entry.layerId;
}

const READY_VERSIONS = { road_surface: "1-test", poi: "1-test", accident: "1-test" };

describe("状態を地図へ伝えた結果", () => {
  beforeEach(() => {
    setTileVersions(READY_VERSIONS);
  });

  describe("面（標高図・土地被覆・起伏）", () => {
    it("表示ONにしたものだけが見えている", () => {
      const { map, handle } = createRecordingMap();

      redrawAllLayers(
        map as never,
        {
          ...baseState(),
          staticLayerVisibility: { elevation: true, landcover: false, hillshade: false },
        } as RedrawAllLayersProps,
      );

      expect(handle.layer(layerIdOf("elevation"))?.visibility).toBe("visible");
      expect(handle.layer(layerIdOf("landcover"))?.visibility).toBe("none");
      expect(handle.layer(layerIdOf("hillshade"))?.visibility).toBe("none");
    });

    it("面は、道路の線より背面にある", () => {
      const { map, handle } = createRecordingMap();

      redrawAllLayers(
        map as never,
        {
          ...baseState(),
          staticLayerVisibility: { elevation: true, roadSurface: true, tunnel: true },
        } as RedrawAllLayersProps,
      );

      const order = handle.layerOrder();
      expect(order.indexOf(layerIdOf("elevation"))).toBeLessThan(order.indexOf(layerIdOf("tunnel")));
    });

    it("スタイルを差し替えても、同じ状態を伝え直せば元へ戻る", () => {
      const { map, handle } = createRecordingMap();
      const state = {
        ...baseState(),
        staticLayerVisibility: { elevation: true, hillshade: true },
      } as RedrawAllLayersProps;
      redrawAllLayers(map as never, state);
      const before = handle.layerOrder();

      handle.dropEverything();
      redrawAllLayers(map as never, state);

      expect(handle.layerOrder()).toEqual(before);
    });
  });

  describe("路面の線", () => {
    it("タイル世代が無い間は、路面のソースを作らない", () => {
      setTileVersions({});
      const { map, handle } = createRecordingMap();

      redrawAllLayers(
        map as never,
        {
          ...baseState(),
          staticLayerVisibility: { roadSurface: true },
        } as RedrawAllLayersProps,
      );

      expect(handle.sources()).not.toContain(ROAD_TILE_SOURCE_ID);
    });

    it("世代が届いた後に同じ状態を伝えると、路面の線が見えている", () => {
      setTileVersions({});
      const { map, handle } = createRecordingMap();
      const state = { ...baseState(), staticLayerVisibility: { roadSurface: true } } as RedrawAllLayersProps;
      redrawAllLayers(map as never, state);

      setTileVersions(READY_VERSIONS);
      redrawAllLayers(map as never, state);

      expect(handle.sources()).toContain(ROAD_TILE_SOURCE_ID);
      expect(handle.layer(ROAD_TILE_LAYER_ID)?.visibility).toBe("visible");
    });

    // 同じ道へ複数の線を重ねると後から描いた方が隠す。ON中の本数から対称に割り付ける。
    it("路面と道路種別を同時に出すと、線が左右へ分かれる", () => {
      const { map, handle } = createRecordingMap();

      redrawAllLayers(
        map as never,
        {
          ...baseState(),
          staticLayerVisibility: { roadSurface: true, roadType: true },
        } as RedrawAllLayersProps,
      );

      const offsets = ROAD_MATERIAL_TRACK_LAYER_IDS.map((id) => handle.layer(id)?.paint["line-offset"]).filter(
        (value) => value !== undefined,
      );
      expect(new Set(offsets).size).toBeGreaterThan(1);
      expect(offsets).toContain(0);
    });

    it("1本だけ出すと、その線は中央に戻る", () => {
      const { map, handle } = createRecordingMap();

      redrawAllLayers(
        map as never,
        {
          ...baseState(),
          staticLayerVisibility: { roadSurface: true, roadType: false },
        } as RedrawAllLayersProps,
      );

      expect(handle.layer(ROAD_TILE_LAYER_ID)?.paint["line-offset"]).toBe(0);
      expect(handle.layer(ROAD_TYPE_LAYER_ID)?.visibility).toBe("none");
    });
  });

  describe("点データ（事故・停止要因POI・補給休憩POI）", () => {
    it("タイル世代が無い間は、点のソースを作らない", () => {
      setTileVersions({});
      const { map, handle } = createRecordingMap();

      redrawAllLayers(
        map as never,
        {
          ...baseState(),
          staticLayerVisibility: { accidents: true, stopPoi: true, supplyPoi: true },
        } as RedrawAllLayersProps,
      );

      expect(handle.sources().filter((id) => id.includes("accident") || id.includes("poi"))).toEqual([]);
    });

    it("停止要因と補給は、同じソースの別レイヤーとして出る", () => {
      const { map, handle } = createRecordingMap();

      redrawAllLayers(
        map as never,
        {
          ...baseState(),
          staticLayerVisibility: { stopPoi: true, supplyPoi: true },
        } as RedrawAllLayersProps,
      );

      const stop = handle.layer(layerIdOf("stopPoi"));
      const supply = handle.layer(layerIdOf("supplyPoi"));
      expect(stop?.visibility).toBe("visible");
      expect(supply?.visibility).toBe("visible");
      expect(stop?.source).toBe(supply?.source);
      expect(stop?.id).not.toBe(supply?.id);
    });
  });

  describe("軸レイヤー（専用way値配信軸）", () => {
    function withValues() {
      const { map, handle } = createRecordingMap();
      redrawAllLayers(
        map as never,
        {
          ...baseState(),
          dedicatedWayValueVisibility: { ded1Axis: true, ded2Axis: true },
        } as RedrawAllLayersProps,
      );
      applyAxisFeatureStateValues(map as never, "ded1Value", new Map([["w1", 3]]));
      applyAxisFeatureStateValues(map as never, "ded2Value", new Map([["w1", 7]]));
      return { map, handle };
    }

    it("片方の軸を消しても、もう片方の値は残る", () => {
      const { map, handle } = withValues();
      const visibility = { ded1Axis: false, ded2Axis: true };

      if (shouldClearDedicatedWayValueFeatureState(visibility)) clearRoadTileFeatureState(map as never);

      expect(handle.featureState(ROAD_TILE_SOURCE_ID, "w1")).toEqual({ ded1Value: 3, ded2Value: 7 });
    });

    it("どの軸も出していない状態にすると、値が消える", () => {
      const { map, handle } = withValues();
      const visibility = { ded1Axis: false, ded2Axis: false };

      if (shouldClearDedicatedWayValueFeatureState(visibility)) clearRoadTileFeatureState(map as never);

      expect(handle.featureState(ROAD_TILE_SOURCE_ID, "w1")).toBeUndefined();
    });

    it("表示ONの軸のレイヤーだけが見えている", () => {
      const { map, handle } = createRecordingMap();

      redrawAllLayers(
        map as never,
        {
          ...baseState(),
          dedicatedWayValueVisibility: { ded1Axis: true, ded2Axis: false },
        } as RedrawAllLayersProps,
      );

      expect(handle.layer(layerIdOf("ded1Axis"))?.visibility).toBe("visible");
      expect(handle.layer(layerIdOf("ded2Axis"))?.visibility).toBe("none");
    });
  });
});
