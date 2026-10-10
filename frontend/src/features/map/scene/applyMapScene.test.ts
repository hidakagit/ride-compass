// @vitest-environment node
import type { FilterSpecification } from "maplibre-gl";
import { describe, expect, it } from "vitest";

import { createRecordingMap, type RecordingMap } from "@/testing/mapTrace/recordingMap";

import { applyMapScene, type MapSceneTarget } from "./applyMapScene";
import {
  EMPTY_MAP_SCENE,
  interactiveSceneLayerIds,
  sceneLayerIdsForHitTarget,
  type MapScene,
  type MapSceneFeatureStateValue,
  type MapSceneLayer,
  type MapSceneSource,
  type MapSceneSourceContent,
  type MapSceneTier,
} from "./mapScene";

/** 地物の状態。本物の `getFeatureState` と同じく、置かれていなければ空として読む。 */
function roadStateOf(handle: RecordingMap, featureId: string): Record<string, unknown> {
  return { ...handle.featureState("roads", featureId) };
}

/** 地図に載っているレイヤー（並び・塗り・配置・絞り込み）とソース（宣言・流し込んだ中身）。 */
function snapshot(handle: RecordingMap): unknown {
  return {
    layers: handle.layerOrder().map((id) => handle.layer(id)),
    sources: handle
      .sources()
      .sort()
      .map((id) => ({ id, spec: handle.sourceSpec(id), content: handle.sourceContent(id) })),
  };
}

const BASEMAP_LAYER_IDS = ["basemap-water", "basemap-road", "basemap-label"];
const BASEMAP_ANCHORS = { roads: "basemap-road", labels: "basemap-label" };
const ROAD_TILES = ["https://tiles.test/v1/{z}/{x}/{y}.pbf"];

/** 呼び出し側が「どう差し替えるか」を宣言する形の一例。 */
function tileContent(tiles: readonly string[]): MapSceneSourceContent {
  return {
    spec: { tiles },
    replace: (source) => {
      (source as { setTiles(tiles: string[]): void }).setTiles([...tiles]);
    },
  };
}

function roadsSource(overrides: Partial<MapSceneSource> = {}): MapSceneSource {
  return {
    id: "roads",
    spec: { type: "vector" },
    content: tileContent(ROAD_TILES),
    sourceLayer: "road",
    ...overrides,
  };
}

const LANDCOVER_SOURCE: MapSceneSource = {
  id: "landcover",
  spec: { type: "raster", tileSize: 256 },
  content: tileContent(["https://tiles.test/lc/{z}/{x}/{y}.png"]),
};

function fillLayer(id: string, color = "#222222"): MapSceneLayer {
  return {
    spec: { id, type: "fill", source: "landcover", paint: { "fill-color": color } },
    tier: "area",
    visible: true,
    hitTargets: [],
  };
}

function lineLayer(id: string, tier: MapSceneTier, overrides: Partial<MapSceneLayer> = {}): MapSceneLayer {
  return {
    spec: {
      id,
      type: "line",
      source: "roads",
      "source-layer": "road",
      paint: { "line-color": "#111111" },
    },
    tier,
    visible: true,
    hitTargets: [],
    ...overrides,
  };
}

function scene(
  layers: readonly MapSceneLayer[],
  sources: readonly MapSceneSource[] = [roadsSource(), LANDCOVER_SOURCE],
): MapScene {
  return { sources, layers };
}

const SCENE_LAYERS: readonly MapSceneLayer[] = [
  fillLayer("landcover-fill"),
  lineLayer("surface-line", "observedLine", { hitTargets: ["road"] }),
  lineLayer("lens-line", "lensLine"),
  lineLayer("poi", "point", { hitTargets: ["poi"] }),
  lineLayer("route", "route", { hitTargets: ["road", "routeSegment"] }),
];

const EXPECTED_ORDER = [
  "basemap-water",
  "landcover-fill",
  "basemap-road",
  "basemap-label",
  "surface-line",
  "lens-line",
  "poi",
  "route",
];

function applied(map: MapSceneTarget, next: MapScene, previous = EMPTY_MAP_SCENE): void {
  applyMapScene(map, { scene: next, previous, basemapAnchors: BASEMAP_ANCHORS });
}

function statesScene(states: ReadonlyMap<string, ReadonlyMap<string, MapSceneFeatureStateValue>>): MapScene {
  return scene(
    [fillLayer("landcover-fill"), lineLayer("axis-line", "observedLine")],
    [roadsSource({ featureStates: states }), LANDCOVER_SOURCE],
  );
}

describe("mapScene", () => {
  it("押せるレイヤーの一覧も、対象ごとの一覧も、同じ宣言から段の順で導ける", () => {
    const shuffled = scene([...SCENE_LAYERS].reverse());

    expect(interactiveSceneLayerIds(shuffled)).toEqual(["surface-line", "poi", "route"]);
    expect(sceneLayerIdsForHitTarget(shuffled, "road")).toEqual(["surface-line", "route"]);
  });
});

describe("applyMapScene", () => {
  it("宣言したソースとレイヤーが、渡した配列の並びによらず段の順で地図に載り、面の段だけ呼び出し側が渡した位置より下へ入る", () => {
    const { map, handle } = createRecordingMap({ basemapLayerIds: BASEMAP_LAYER_IDS });

    applied(map, scene([...SCENE_LAYERS].reverse()));

    expect(handle.layerOrder()).toEqual(EXPECTED_ORDER);
    expect(handle.sourceSpec("roads")).toEqual({ type: "vector", tiles: ROAD_TILES });
    expect(handle.layer("surface-line")?.visibility).toBe("visible");
  });

  it("文字に場所を譲る点の段は、呼び出し側が渡した基礎地図の文字の位置より下へ入る", () => {
    const { map, handle } = createRecordingMap({ basemapLayerIds: BASEMAP_LAYER_IDS });

    applied(map, scene([...SCENE_LAYERS, lineLayer("thinned-poi", "pointUnderLabels")].reverse()));

    expect(handle.layerOrder()).toEqual([
      "basemap-water",
      "landcover-fill",
      "basemap-road",
      "thinned-poi",
      "basemap-label",
      "surface-line",
      "lens-line",
      "poi",
      "route",
    ]);
  });

  it("あとから足したレイヤーも段の順の位置へ入る", () => {
    const { map, handle } = createRecordingMap({ basemapLayerIds: BASEMAP_LAYER_IDS });
    const before = scene([lineLayer("axis-line", "observedLine"), lineLayer("route", "route")]);
    applied(map, before);

    applied(
      map,
      scene([
        lineLayer("axis-line", "observedLine"),
        lineLayer("route", "route"),
        lineLayer("tunnel-line", "observedLine"),
        fillLayer("landcover-fill"),
      ]),
      before,
    );

    expect(handle.layerOrder()).toEqual([
      "basemap-water",
      "landcover-fill",
      "basemap-road",
      "basemap-label",
      "axis-line",
      "tunnel-line",
      "route",
    ]);
  });

  it("scene が名指ししていない基礎地図のレイヤーは、scene を空にしても残る", () => {
    const { map, handle } = createRecordingMap({ basemapLayerIds: BASEMAP_LAYER_IDS });
    const first = scene(SCENE_LAYERS);
    applied(map, first);

    applied(map, EMPTY_MAP_SCENE, first);

    expect(handle.layerOrder()).toEqual(BASEMAP_LAYER_IDS);
    expect(handle.sources()).toEqual([]);
  });

  it("表示ON/OFF・絞り込み・paint は当て直した後の宣言どおりになる", () => {
    const { map, handle } = createRecordingMap({ basemapLayerIds: BASEMAP_LAYER_IDS });
    const before = scene([
      lineLayer("surface-line", "observedLine", {
        spec: {
          id: "surface-line",
          type: "line",
          source: "roads",
          "source-layer": "road",
          paint: { "line-color": "#111111", "line-opacity": 0.4 },
        },
        filter: ["==", ["get", "kind"], "paved"] as FilterSpecification,
      }),
    ]);
    applied(map, before);

    applied(
      map,
      scene([
        lineLayer("surface-line", "observedLine", {
          spec: {
            id: "surface-line",
            type: "line",
            source: "roads",
            "source-layer": "road",
            paint: { "line-color": "#222222" },
          },
          visible: false,
        }),
      ]),
      before,
    );

    const layer = handle.layer("surface-line");
    expect(layer?.paint).toEqual({ "line-color": "#222222" });
    expect(layer?.visibility).toBe("none");
    expect(layer?.filter).toBeUndefined();
  });

  it("中身だけが変わったソースは、作り直さずに差し替わる", () => {
    const { map, handle } = createRecordingMap({ basemapLayerIds: BASEMAP_LAYER_IDS });
    const before = scene([lineLayer("axis-line", "observedLine")]);
    applied(map, before);
    const roads = map.getSource("roads");

    const nextTiles = ["https://tiles.test/v2/{z}/{x}/{y}.pbf"];
    applied(
      map,
      scene(
        [lineLayer("axis-line", "observedLine")],
        [roadsSource({ content: tileContent(nextTiles) }), LANDCOVER_SOURCE],
      ),
      before,
    );

    expect(map.getSource("roads")).toBe(roads);
    expect(handle.sourceContent("roads")?.tiles).toEqual(nextTiles);
  });

  it("作り直せない宣言が変わったソースは作り直され、レイヤーとfeature-stateも戻る", () => {
    const { map, handle } = createRecordingMap({ basemapLayerIds: BASEMAP_LAYER_IDS });
    const states = new Map([["windValue", new Map([["w1", 3]])]]);
    const before = scene([lineLayer("axis-line", "observedLine")], [roadsSource({ featureStates: states })]);
    applied(map, before);
    const roads = map.getSource("roads");

    applied(
      map,
      scene(
        [lineLayer("axis-line", "observedLine")],
        [roadsSource({ spec: { type: "vector", maxzoom: 15 }, featureStates: states })],
      ),
      before,
    );

    expect(map.getSource("roads")).not.toBe(roads);
    expect(handle.sourceSpec("roads")).toEqual({ type: "vector", maxzoom: 15, tiles: ROAD_TILES });
    expect(handle.layer("axis-line")?.paint).toEqual({ "line-color": "#111111" });
    expect(roadStateOf(handle, "w1")).toEqual({ windValue: 3 });
  });

  it("1つのキーだけが消えても、同じソースに残る別のキーの値は消えない", () => {
    const { map, handle } = createRecordingMap({ basemapLayerIds: BASEMAP_LAYER_IDS });
    const before = statesScene(
      new Map([
        [
          "windValue",
          new Map([
            ["w1", 1],
            ["w2", 2],
          ]),
        ],
        ["gradientValue", new Map([["w1", 5]])],
      ]),
    );
    applied(map, before);
    expect(roadStateOf(handle, "w1")).toEqual({ windValue: 1, gradientValue: 5 });
    expect(roadStateOf(handle, "w2")).toEqual({ windValue: 2 });

    applied(map, statesScene(new Map([["gradientValue", new Map([["w1", 5]])]])), before);

    expect(roadStateOf(handle, "w1")).toEqual({ gradientValue: 5 });
    expect(roadStateOf(handle, "w2")).toEqual({});
  });

  it("feature-state が1つも残らないときだけ、ソース単位で消える", () => {
    const { map, handle } = createRecordingMap({ basemapLayerIds: BASEMAP_LAYER_IDS });
    const before = statesScene(
      new Map([
        ["windValue", new Map([["w1", 1]])],
        ["gradientValue", new Map([["w2", 5]])],
      ]),
    );
    applied(map, before);

    applied(map, statesScene(new Map()), before);

    expect(roadStateOf(handle, "w1")).toEqual({});
    expect(roadStateOf(handle, "w2")).toEqual({});
  });

  it("途中の scene を経由しても、同じ scene を当てた地図と同じ状態になる", () => {
    const first = scene([
      fillLayer("landcover-fill", "#999999"),
      lineLayer("axis-line", "observedLine"),
      lineLayer("surface-line", "observedLine"),
      lineLayer("route", "route"),
    ]);
    const second = scene([
      fillLayer("landcover-fill"),
      lineLayer("axis-line", "observedLine", { visible: false }),
      lineLayer("tunnel-line", "observedLine"),
      lineLayer("poi", "point", { hitTargets: ["poi"] }),
      lineLayer("route", "route"),
    ]);

    const stepwise = createRecordingMap({ basemapLayerIds: BASEMAP_LAYER_IDS });
    applied(stepwise.map, first);
    applied(stepwise.map, second, first);

    const direct = createRecordingMap({ basemapLayerIds: BASEMAP_LAYER_IDS });
    applied(direct.map, second);

    expect(stepwise.handle.layerOrder()).toEqual(direct.handle.layerOrder());
    expect(snapshot(stepwise.handle)).toEqual(snapshot(direct.handle));
  });
});
