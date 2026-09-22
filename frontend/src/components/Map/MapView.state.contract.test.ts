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
  DYNAMIC_WEATHER_RENDERERS,
  ROAD_MATERIAL_TRACK_LAYER_IDS,
  ROAD_TILE_LAYER_ID,
  ROAD_TILE_SOURCE_ID,
  ROAD_TYPE_LAYER_ID,
  applyAxisFeatureStateValues,
  buildAxisOverlayLayers,
  buildStaticOverlayLayers,
  clearRoadTileFeatureState,
  TILE_VERSION_GATED_SOURCE_IDS,
  applyDynamicWeatherState,
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
  });

  describe("点データ（事故・停止要因POI・補給休憩POI）", () => {
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
  });
});

describe("レイヤーを横断する要求", () => {
  const EMPTY_GEOJSON: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

  /** 宣言された描き方に合う中身を、全グループ・全ソースぶん作る。**名指ししない**
   * ——要素が増えたらそのまま対象になる。 */
  function everyDynamicWeatherPayload() {
    const groups = DYNAMIC_WEATHER_RENDERERS as unknown as Record<string, Record<string, Record<string, unknown>>>;
    return Object.entries(groups).map(([groupId, groupSpec]) => {
      const state: Record<string, unknown> = {};
      for (const [sourceId, spec] of Object.entries(groupSpec)) {
        if (!spec) continue;
        const payload = spec.raster
          ? { kind: "rasterTile", tileUrlTemplate: "https://example.test/{z}/{x}/{y}.png" }
          : spec.vector
            ? { kind: "vectorTile", tileUrlTemplate: "https://example.test/{z}/{x}/{y}.pbf" }
            : spec.gridFill
              ? { kind: "gridFill", geojson: EMPTY_GEOJSON }
              : spec.gridMark
                ? { kind: "gridMark", geojson: EMPTY_GEOJSON }
                : undefined;
        state[sourceId] = { visible: true, payload };
      }
      return [groupId, state] as const;
    });
  }

  /** カタログにある全レイヤーと、ルート・帯・比較スロットを出した状態。 */
  function everythingVisible(): RedrawAllLayersProps {
    const visibility: Record<string, boolean> = {};
    for (const layer of CATALOG) visibility[layer.id] = true;
    const mode = { id: "difficulty", label: "難易度", colorExpression: ["literal", "#16a34a"], legend: [] };
    const candidate = {
      id: "a",
      geometry: {
        type: "LineString",
        coordinates: [
          [139.7, 35.6],
          [139.71, 35.61],
        ],
      },
      segments: [
        {
          start_longitude: 139.7,
          start_latitude: 35.6,
          end_longitude: 139.71,
          end_latitude: 35.61,
          geometry: {
            type: "LineString",
            coordinates: [
              [139.7, 35.6],
              [139.71, 35.61],
            ],
          },
        },
      ],
    };
    return {
      ...baseState(),
      staticLayerVisibility: visibility,
      dedicatedWayValueVisibility: visibility,
      axisVisibility: visibility,
      routes: [candidate],
      selectedRouteId: "a",
      routeLayerOn: true,
      routeStyleModes: [mode],
      routeStyleModeId: "difficulty",
      experimentSlots: [{ color: "#16a34a", topCandidate: candidate }],
    } as unknown as RedrawAllLayersProps;
  }

  function showEverything(map: unknown, state: RedrawAllLayersProps) {
    redrawAllLayers(map as never, state);
    for (const [groupId, groupState] of everyDynamicWeatherPayload()) {
      applyDynamicWeatherState(
        map as never,
        groupId as never,
        DYNAMIC_WEATHER_RENDERERS[groupId as keyof typeof DYNAMIC_WEATHER_RENDERERS],
        groupState as never,
      );
    }
  }

  // 「差し替え後に戻るか」はレイヤーごとの性質ではないので、家族ごとに繰り返さず
  // **カタログ全件を載せた状態で1回**見る。新しいレイヤーが増えればそのまま対象になる。
  it("スタイルを差し替えても、同じ状態を伝え直せば元へ戻る", () => {
    const { map, handle } = createRecordingMap();
    const state = everythingVisible();
    showEverything(map, state);
    const before = handle.layerOrder();
    // 空振りしていないこと（載っていなければ比較は常に通る）。
    expect(before.length).toBeGreaterThan(CATALOG.length);

    handle.dropEverything();
    showEverything(map, state);

    expect(handle.layerOrder()).toEqual(before);
  });

  // 世代が届く前にソースを作ると、世代の違う中身がブラウザのキャッシュへ載って以後ずっと残る。
  // 対象は「世代を要る情報源」の宣言から導く。
  it("タイル世代が無い間は、世代を要るソースを1つも作らない", () => {
    setTileVersions({});
    const { map, handle } = createRecordingMap();

    showEverything(map, everythingVisible());

    expect(TILE_VERSION_GATED_SOURCE_IDS.length).toBeGreaterThan(0);
    for (const sourceId of TILE_VERSION_GATED_SOURCE_IDS) {
      expect(handle.sources()).not.toContain(sourceId);
    }
  });

  it("世代が届いた後に同じ状態を伝えると、世代を要るソースが揃う", () => {
    setTileVersions({});
    const { map, handle } = createRecordingMap();
    const state = everythingVisible();
    showEverything(map, state);

    setTileVersions(READY_VERSIONS);
    showEverything(map, state);

    for (const sourceId of TILE_VERSION_GATED_SOURCE_IDS) {
      expect(handle.sources()).toContain(sourceId);
    }
  });
});
