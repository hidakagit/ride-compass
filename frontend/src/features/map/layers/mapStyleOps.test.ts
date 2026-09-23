// @vitest-environment node
import type { Map as MapLibreMap } from "maplibre-gl";
import { describe, expect, it, vi } from "vitest";

import {
  areaLayerAnchor,
  prepareBasemapForAreaLayers,
  resetBasemapAreaLayerPreparation,
  runWhenStyleReady,
} from "./mapStyleOps";

type StyleLayer = { id: string; type: string; "source-layer"?: string };

/** スタイルのレイヤー列を持ち、`moveLayer`で実際に並べ替える地図。 */
function fakeMap(initial: StyleLayer[] | undefined) {
  let layers = initial;
  const loadListeners: (() => void)[] = [];
  const map = {
    getStyle: () => (layers === undefined ? undefined : { layers }),
    getLayer: (id: string) => layers?.find((layer) => layer.id === id),
    moveLayer: vi.fn((id: string, beforeId: string) => {
      if (!layers) return;
      const moving = layers.find((layer) => layer.id === id)!;
      const rest = layers.filter((layer) => layer.id !== id);
      rest.splice(
        rest.findIndex((layer) => layer.id === beforeId),
        0,
        moving,
      );
      layers = rest;
    }),
    once: (event: string, listener: () => void) => {
      if (event === "load") loadListeners.push(listener);
    },
  };
  return {
    map: map as unknown as MapLibreMap,
    moveLayer: map.moveLayer,
    order: () => layers?.map((layer) => layer.id),
    setLayers: (next: StyleLayer[] | undefined) => {
      layers = next;
    },
    fireLoad: () => loadListeners.splice(0).forEach((listener) => listener()),
  };
}

// 基礎地図の並び: 土地の塗り → 道路網 → 道路より後ろに置かれた建物の面 → 地名
const BASEMAP: StyleLayer[] = [
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
    const { map, order } = fakeMap(BASEMAP.map((layer) => ({ ...layer })));
    prepareBasemapForAreaLayers(map);
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
    const { map, moveLayer, setLayers } = fakeMap(BASEMAP.map((layer) => ({ ...layer })));
    prepareBasemapForAreaLayers(map);
    prepareBasemapForAreaLayers(map);
    expect(moveLayer).toHaveBeenCalledTimes(2);

    setLayers([
      { id: "water", type: "fill", "source-layer": "water" },
      { id: "highway", type: "line", "source-layer": "transportation" },
    ]);
    resetBasemapAreaLayerPreparation(map);
    prepareBasemapForAreaLayers(map);
    expect(areaLayerAnchor(map)).toBe("highway");
  });

  it("スタイルを読み込み中（読めない間）は決めず、読めるようになってから決める", () => {
    const { map, setLayers } = fakeMap(undefined);
    prepareBasemapForAreaLayers(map);
    expect(areaLayerAnchor(map)).toBeUndefined();
    setLayers(BASEMAP.map((layer) => ({ ...layer })));
    prepareBasemapForAreaLayers(map);
    expect(areaLayerAnchor(map)).toBe("road_minor");
  });

  it("道路網を持たないスタイルは差し込み先なし（面は最前面へ積まれる）", () => {
    const { map } = fakeMap([{ id: "background", type: "background" }]);
    prepareBasemapForAreaLayers(map);
    expect(areaLayerAnchor(map)).toBeUndefined();
  });

  it("記録した位置が今のスタイルから消えていれば使わない（無いidへ差し込むと例外になる）", () => {
    const { map, setLayers } = fakeMap(BASEMAP.map((layer) => ({ ...layer })));
    prepareBasemapForAreaLayers(map);
    setLayers([{ id: "background", type: "background" }]);
    expect(areaLayerAnchor(map)).toBeUndefined();
  });
});

describe("runWhenStyleReady（スタイルが一度読めたら実行）", () => {
  it("初回の読み込みを待って実行し、以後は待たずにすぐ実行する", () => {
    const { map, fireLoad } = fakeMap(BASEMAP);
    const first = vi.fn();
    runWhenStyleReady(map, first);
    expect(first).not.toHaveBeenCalled();
    fireLoad();
    expect(first).toHaveBeenCalledTimes(1);

    const later = vi.fn();
    runWhenStyleReady(map, later);
    expect(later).toHaveBeenCalledTimes(1);
  });
});
