import { Map as MapLibreMap } from "maplibre-gl";
import { describe, expect, it, vi } from "vitest";

import { mapOnScreen } from "@/testing/maplibre";
import { matchesFilter } from "@/testing/mapExpressions";
import type { StyleLayer } from "@/testing/mapTrace/recordingMap";

vi.mock("maplibre-gl", () => import("@/testing/maplibre"));

import { areaLayerAnchor, prepareBasemap, resetBasemapPreparation, runWhenStyleReady } from "./mapStyleOps";

/** スタイル`layers`を読み込んだ地図（undefined なら読み込み中）。 */
function drawMap(layers: readonly StyleLayer[] | undefined) {
  const map = new MapLibreMap({ container: document.createElement("div"), style: "basemap", zoom: 14 });
  const screen = mapOnScreen();
  screen.loadStyle(layers);
  return { map, screen, order: () => screen.visibleLayerIds() };
}

// 基礎地図の並び: 土地の塗り → 道路網 → 道路より後ろに置かれた建物の面 → 地名
const BASEMAP: readonly StyleLayer[] = [
  { id: "background", type: "background" },
  { id: "park", type: "fill", "source-layer": "park" },
  { id: "road_minor", type: "line", "source-layer": "transportation" },
  { id: "road_major", type: "line", "source-layer": "transportation" },
  { id: "building", type: "fill", "source-layer": "building" },
  { id: "building-3d", type: "fill-extrusion", "source-layer": "building" },
  { id: "place_label", type: "symbol", "source-layer": "place" },
];

describe("面レイヤーの差し込み位置", () => {
  it("道路網を描き始める最初のレイヤーの下に面を入れ、道路より後ろの面（建物）はその手前へ動かす", () => {
    const { map, order } = drawMap(BASEMAP);
    prepareBasemap(map);
    expect(areaLayerAnchor(map)).toBe("road_minor");
    expect(order()).toEqual([
      "background",
      "park",
      "building",
      "building-3d",
      "road_minor",
      "road_major",
      "place_label",
    ]);
  });

  it("同じスタイルには1度だけ当て、スタイルを差し替えたら新しいスタイルへ当て直す", () => {
    const { map, screen } = drawMap(BASEMAP);
    prepareBasemap(map);

    const replaced: StyleLayer[] = [
      { id: "water", type: "fill", "source-layer": "water" },
      { id: "highway", type: "line", "source-layer": "transportation" },
    ];
    screen.loadStyle(replaced);
    prepareBasemap(map);
    expect(areaLayerAnchor(map)).toBeUndefined();

    resetBasemapPreparation(map);
    prepareBasemap(map);
    expect(areaLayerAnchor(map)).toBe("highway");
  });

  it("スタイルを読み込み中（読めない間）は決めず、読めるようになってから決める", () => {
    const { map, screen } = drawMap(undefined);
    prepareBasemap(map);
    expect(areaLayerAnchor(map)).toBeUndefined();
    screen.loadStyle(BASEMAP);
    prepareBasemap(map);
    expect(areaLayerAnchor(map)).toBe("road_minor");
  });

  it("道路網を持たないスタイルは差し込み先なし（面は最前面へ積まれる）", () => {
    const { map } = drawMap([{ id: "background", type: "background" }]);
    prepareBasemap(map);
    expect(areaLayerAnchor(map)).toBeUndefined();
  });

  it("記録した位置が今のスタイルから消えていれば使わない（無いidへ差し込むと例外になる）", () => {
    const { map, screen } = drawMap(BASEMAP);
    prepareBasemap(map);
    screen.loadStyle([{ id: "background", type: "background" }]);
    expect(areaLayerAnchor(map)).toBeUndefined();
  });
});

describe("基礎地図の店・施設", () => {
  // libertyの店・施設のレイヤーの絞り（OpenFreeMapのスタイルから写した）。点を順位で3段に分け、駅・バス・空港は別に描く。
  const POINT = ["match", ["geometry-type"], ["MultiPoint", "Point"], true, false];
  const POI_LAYERS: readonly StyleLayer[] = [
    { id: "road_minor", type: "line", "source-layer": "transportation" },
    { id: "poi_r20", type: "symbol", "source-layer": "poi", filter: ["all", POINT, [">=", ["get", "rank"], 20]] },
    {
      id: "poi_r7",
      type: "symbol",
      "source-layer": "poi",
      filter: ["all", POINT, [">=", ["get", "rank"], 7], ["<", ["get", "rank"], 20]],
    },
    {
      id: "poi_r1",
      type: "symbol",
      "source-layer": "poi",
      filter: ["all", POINT, [">=", ["get", "rank"], 1], ["<", ["get", "rank"], 7]],
    },
    {
      id: "poi_transit",
      type: "symbol",
      "source-layer": "poi",
      filter: ["match", ["get", "class"], ["airport", "bus", "rail"], true, false],
    },
  ];

  /** その地物（点）を描くレイヤーのid。 */
  function drawnBy(map: MapLibreMap, properties: Record<string, unknown>): string[] {
    return map
      .getStyle()
      .layers.flatMap((layer) =>
        "source-layer" in layer && layer["source-layer"] === "poi" && matchesFilter(layer.filter, properties, 1)
          ? [layer.id]
          : [],
      );
  }

  it("コンビニ（補給の点が別の出どころから出す）は描かず、ほかの店・施設と駅はそのまま描く", () => {
    const { map } = drawMap(POI_LAYERS);
    prepareBasemap(map);

    // OpenMapTilesのスキーマで、OSMの`shop=convenience`は`class=shop`・`subclass=convenience`になる。
    expect(drawnBy(map, { class: "shop", subclass: "convenience", rank: 3 })).toEqual([]);
    expect(drawnBy(map, { class: "shop", subclass: "convenience", rank: 25 })).toEqual([]);
    expect(drawnBy(map, { class: "shop", subclass: "bakery", rank: 3 })).toEqual(["poi_r1"]);
    expect(drawnBy(map, { class: "hospital", subclass: "hospital", rank: 8 })).toEqual(["poi_r7"]);
    expect(drawnBy(map, { class: "rail", subclass: "station", rank: 25 })).toEqual(["poi_r20", "poi_transit"]);
  });

  it("同じスタイルへ何度当てても絞りを重ねない", () => {
    const { map } = drawMap(POI_LAYERS);
    prepareBasemap(map);
    const once = map.getStyle().layers;
    prepareBasemap(map);
    expect(map.getStyle().layers).toEqual(once);
  });
});

describe("runWhenStyleReady（スタイルが一度読めたら実行）", () => {
  it("初回の読み込みを待って実行し、以後は待たずにすぐ実行する", () => {
    const { map, screen } = drawMap(BASEMAP);
    const first = vi.fn();
    runWhenStyleReady(map, first);
    expect(first).not.toHaveBeenCalled();
    screen.emit("load");
    expect(first).toHaveBeenCalledTimes(1);

    const later = vi.fn();
    runWhenStyleReady(map, later);
    expect(later).toHaveBeenCalledTimes(1);
  });
});
