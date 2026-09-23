// @vitest-environment node
import type { FeatureIdentifier, FilterSpecification, LayerSpecification, SourceSpecification } from "maplibre-gl";
import { describe, expect, it } from "vitest";

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

type FakeSource = { readonly id: string; readonly spec: Record<string, unknown> };

type FakeLayer = {
  readonly id: string;
  paint: Record<string, unknown>;
  layout: Record<string, unknown>;
  filter: unknown;
};

/** MapLibre の地図の代役。scene が触る操作だけを持ち、最後の状態を読み出せる。 */
class FakeMap implements MapSceneTarget {
  readonly layers: FakeLayer[] = [];
  readonly sources = new Map<string, FakeSource>();
  private readonly states = new Map<string, Map<string, Record<string, MapSceneFeatureStateValue>>>();

  constructor(basemapLayerIds: readonly string[] = []) {
    for (const id of basemapLayerIds) {
      this.layers.push({ id, paint: {}, layout: {}, filter: undefined });
    }
  }

  getSource(id: string): FakeSource | undefined {
    return this.sources.get(id);
  }

  addSource(id: string, source: SourceSpecification): void {
    this.sources.set(id, {
      id,
      spec: { ...(source as unknown as Record<string, unknown>) },
    });
  }

  removeSource(id: string): void {
    this.sources.delete(id);
  }

  addLayer(layer: LayerSpecification, beforeId?: string): void {
    const spec = layer as unknown as Record<string, unknown>;
    const record: FakeLayer = {
      id: layer.id,
      paint: { ...((spec.paint as Record<string, unknown>) ?? {}) },
      layout: { ...((spec.layout as Record<string, unknown>) ?? {}) },
      filter: spec.filter,
    };
    if (beforeId === undefined) this.layers.push(record);
    else this.layers.splice(this.indexOf(beforeId), 0, record);
  }

  removeLayer(id: string): void {
    this.layers.splice(this.indexOf(id), 1);
  }

  setFilter(layerId: string, filter?: FilterSpecification | null): void {
    this.layer(layerId).filter = filter ?? undefined;
  }

  setPaintProperty(layerId: string, name: string, value: unknown): void {
    assignOrDelete(this.layer(layerId).paint, name, value);
  }

  setLayoutProperty(layerId: string, name: string, value: unknown): void {
    assignOrDelete(this.layer(layerId).layout, name, value);
  }

  setFeatureState(target: FeatureIdentifier, state: Record<string, MapSceneFeatureStateValue>): void {
    const bucket = this.bucket(target);
    const id = String(target.id);
    bucket.set(id, { ...(bucket.get(id) ?? {}), ...state });
  }

  removeFeatureState(target: FeatureIdentifier, key?: string): void {
    const bucket = this.bucket(target);
    if (target.id === undefined) {
      bucket.clear();
      return;
    }
    const id = String(target.id);
    const current = bucket.get(id);
    if (key === undefined || current === undefined) {
      bucket.delete(id);
      return;
    }
    delete current[key];
    if (Object.keys(current).length === 0) bucket.delete(id);
  }

  order(): string[] {
    return this.layers.map((layer) => layer.id);
  }

  layer(id: string): FakeLayer {
    const record = this.layers.find((entry) => entry.id === id);
    if (record === undefined) throw new Error(`レイヤーが無い: ${id}`);
    return record;
  }

  featureStatesOf(source: string, sourceLayer?: string): Record<string, Record<string, MapSceneFeatureStateValue>> {
    return Object.fromEntries(this.states.get(bucketKey({ source, sourceLayer })) ?? new Map());
  }

  snapshot(): unknown {
    return {
      layers: this.layers.map(({ id, paint, layout, filter }) => ({
        id,
        paint,
        layout,
        filter,
      })),
      sources: [...this.sources.values()].sort((a, b) => a.id.localeCompare(b.id)),
      states: [...this.states.entries()]
        .map(([key, bucket]) => [key, Object.fromEntries(bucket)] as const)
        .sort((a, b) => a[0].localeCompare(b[0])),
    };
  }

  private indexOf(id: string): number {
    return this.layers.indexOf(this.layer(id));
  }

  private bucket(target: FeatureIdentifier): Map<string, Record<string, MapSceneFeatureStateValue>> {
    const key = bucketKey(target);
    const existing = this.states.get(key);
    if (existing !== undefined) return existing;
    const created = new Map<string, Record<string, MapSceneFeatureStateValue>>();
    this.states.set(key, created);
    return created;
  }
}

function bucketKey(target: { source: string; sourceLayer?: string }): string {
  return `${target.source}/${target.sourceLayer ?? ""}`;
}

function assignOrDelete(record: Record<string, unknown>, name: string, value: unknown): void {
  if (value === null) delete record[name];
  else record[name] = value;
}

const BASEMAP_LAYER_IDS = ["basemap-water", "basemap-road", "basemap-label"];
const AREA_BEFORE_ID = "basemap-road";
const ROAD_TILES = ["https://tiles.test/v1/{z}/{x}/{y}.pbf"];

/** 呼び出し側が「どう差し替えるか」を宣言する形の一例。 */
function tileContent(tiles: readonly string[]): MapSceneSourceContent {
  return {
    spec: { tiles },
    replace: (source) => {
      (source as FakeSource).spec.tiles = tiles;
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
    role: id,
    spec: { id, type: "fill", source: "landcover", paint: { "fill-color": color } },
    tier: "area",
    visible: true,
    hitTargets: [],
  };
}

function lineLayer(id: string, tier: MapSceneTier, overrides: Partial<MapSceneLayer> = {}): MapSceneLayer {
  return {
    role: id,
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

function applied(map: FakeMap, next: MapScene, previous = EMPTY_MAP_SCENE): void {
  applyMapScene(map, { scene: next, previous, areaLayerBeforeId: AREA_BEFORE_ID });
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
    expect(sceneLayerIdsForHitTarget(shuffled, "poi")).toEqual(["poi"]);
  });
});

describe("applyMapScene", () => {
  it("宣言したソースとレイヤーが地図に載り、面の段だけ呼び出し側が渡した位置より下へ入る", () => {
    const map = new FakeMap(BASEMAP_LAYER_IDS);

    applied(map, scene(SCENE_LAYERS));

    expect(map.order()).toEqual(EXPECTED_ORDER);
    expect(map.getSource("roads")?.spec).toEqual({ type: "vector", tiles: ROAD_TILES });
    expect(map.layer("surface-line").layout).toEqual({ visibility: "visible" });
  });

  it("重なりは段の宣言だけで決まり、渡した配列の並びには依存しない", () => {
    const map = new FakeMap(BASEMAP_LAYER_IDS);

    applied(map, scene([...SCENE_LAYERS].reverse()));

    expect(map.order()).toEqual(EXPECTED_ORDER);
  });

  it("あとから足したレイヤーも段の順の位置へ入る", () => {
    const map = new FakeMap(BASEMAP_LAYER_IDS);
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

    expect(map.order()).toEqual([
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
    const map = new FakeMap(BASEMAP_LAYER_IDS);
    const first = scene(SCENE_LAYERS);
    applied(map, first);

    applied(map, EMPTY_MAP_SCENE, first);

    expect(map.order()).toEqual(BASEMAP_LAYER_IDS);
    expect([...map.sources.keys()]).toEqual([]);
  });

  it("表示ON/OFF・絞り込み・paint は当て直した後の宣言どおりになる", () => {
    const map = new FakeMap(BASEMAP_LAYER_IDS);
    const before = scene([
      lineLayer("surface-line", "observedLine", {
        role: "surface-line",
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
          role: "surface-line",
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

    const layer = map.layer("surface-line");
    expect(layer.paint).toEqual({ "line-color": "#222222" });
    expect(layer.layout).toEqual({ visibility: "none" });
    expect(layer.filter).toBeUndefined();
  });

  it("中身だけが変わったソースは、作り直さずに差し替わる", () => {
    const map = new FakeMap(BASEMAP_LAYER_IDS);
    const before = scene([lineLayer("axis-line", "observedLine")]);
    applied(map, before);
    const handle = map.getSource("roads");

    const nextTiles = ["https://tiles.test/v2/{z}/{x}/{y}.pbf"];
    applied(
      map,
      scene(
        [lineLayer("axis-line", "observedLine")],
        [roadsSource({ content: tileContent(nextTiles) }), LANDCOVER_SOURCE],
      ),
      before,
    );

    expect(map.getSource("roads")).toBe(handle);
    expect(map.getSource("roads")?.spec.tiles).toEqual(nextTiles);
  });

  it("作り直せない宣言が変わったソースは作り直され、レイヤーとfeature-stateも戻る", () => {
    const map = new FakeMap(BASEMAP_LAYER_IDS);
    const states = new Map([["windValue", new Map([["w1", 3]])]]);
    const before = scene([lineLayer("axis-line", "observedLine")], [roadsSource({ featureStates: states })]);
    applied(map, before);
    const handle = map.getSource("roads");

    applied(
      map,
      scene(
        [lineLayer("axis-line", "observedLine")],
        [roadsSource({ spec: { type: "vector", maxzoom: 15 }, featureStates: states })],
      ),
      before,
    );

    expect(map.getSource("roads")).not.toBe(handle);
    expect(map.getSource("roads")?.spec.tiles).toEqual(ROAD_TILES);
    expect(map.layer("axis-line").paint).toEqual({ "line-color": "#111111" });
    expect(map.featureStatesOf("roads", "road")).toEqual({ w1: { windValue: 3 } });
  });

  it("1つのキーだけが消えても、同じソースに残る別のキーの値は消えない", () => {
    const map = new FakeMap(BASEMAP_LAYER_IDS);
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
    expect(map.featureStatesOf("roads", "road")).toEqual({
      w1: { windValue: 1, gradientValue: 5 },
      w2: { windValue: 2 },
    });

    applied(map, statesScene(new Map([["gradientValue", new Map([["w1", 5]])]])), before);

    expect(map.featureStatesOf("roads", "road")).toEqual({ w1: { gradientValue: 5 } });
  });

  it("feature-state が1つも残らないときだけ、ソース単位で消える", () => {
    const map = new FakeMap(BASEMAP_LAYER_IDS);
    const before = statesScene(
      new Map([
        ["windValue", new Map([["w1", 1]])],
        ["gradientValue", new Map([["w2", 5]])],
      ]),
    );
    applied(map, before);

    applied(map, statesScene(new Map()), before);

    expect(map.featureStatesOf("roads", "road")).toEqual({});
  });

  it("前回を空にして当てると、スタイルを差し替えた後の地図へ scene 全体が作り直される", () => {
    const restyled = new FakeMap(BASEMAP_LAYER_IDS);

    applied(restyled, statesScene(new Map([["windValue", new Map([["w1", 7]])]])));

    expect(restyled.order()).toContain("axis-line");
    expect(restyled.getSource("roads")?.spec.tiles).toEqual(ROAD_TILES);
    expect(restyled.featureStatesOf("roads", "road")).toEqual({ w1: { windValue: 7 } });
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

    const stepwise = new FakeMap(BASEMAP_LAYER_IDS);
    applied(stepwise, first);
    applied(stepwise, second, first);

    const direct = new FakeMap(BASEMAP_LAYER_IDS);
    applied(direct, second);

    expect(stepwise.order()).toEqual(direct.order());
    expect(stepwise.snapshot()).toEqual(direct.snapshot());
  });
});
