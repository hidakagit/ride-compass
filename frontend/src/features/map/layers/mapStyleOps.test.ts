import { Map as MapLibreMap } from "maplibre-gl";
import { describe, expect, it, vi } from "vitest";

import { mapOnScreen } from "@/testing/maplibre";
import type { StyleLayer } from "@/testing/mapTrace/recordingMap";

vi.mock("maplibre-gl", () => import("@/testing/maplibre"));

import {
  areaLayerAnchor,
  prepareBasemapForAreaLayers,
  resetBasemapAreaLayerPreparation,
  runWhenStyleReady,
} from "./mapStyleOps";

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
    const { map, screen } = drawMap(BASEMAP);
    prepareBasemapForAreaLayers(map);

    const replaced: StyleLayer[] = [
      { id: "water", type: "fill", "source-layer": "water" },
      { id: "highway", type: "line", "source-layer": "transportation" },
    ];
    screen.loadStyle(replaced);
    prepareBasemapForAreaLayers(map);
    expect(areaLayerAnchor(map)).toBeUndefined();

    resetBasemapAreaLayerPreparation(map);
    prepareBasemapForAreaLayers(map);
    expect(areaLayerAnchor(map)).toBe("highway");
  });

  it("スタイルを読み込み中（読めない間）は決めず、読めるようになってから決める", () => {
    const { map, screen } = drawMap(undefined);
    prepareBasemapForAreaLayers(map);
    expect(areaLayerAnchor(map)).toBeUndefined();
    screen.loadStyle(BASEMAP);
    prepareBasemapForAreaLayers(map);
    expect(areaLayerAnchor(map)).toBe("road_minor");
  });

  it("道路網を持たないスタイルは差し込み先なし（面は最前面へ積まれる）", () => {
    const { map } = drawMap([{ id: "background", type: "background" }]);
    prepareBasemapForAreaLayers(map);
    expect(areaLayerAnchor(map)).toBeUndefined();
  });

  it("記録した位置が今のスタイルから消えていれば使わない（無いidへ差し込むと例外になる）", () => {
    const { map, screen } = drawMap(BASEMAP);
    prepareBasemapForAreaLayers(map);
    screen.loadStyle([{ id: "background", type: "background" }]);
    expect(areaLayerAnchor(map)).toBeUndefined();
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
