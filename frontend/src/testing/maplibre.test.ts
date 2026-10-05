/**
 * `testing/maplibre.ts`——`maplibre-gl` の代役。地図の部品が呼ぶ形で渡したものが、テストの読む値と起こす操作に
 * そのまま出ること（代役が曲がると、頼る地図のテストが同じ向きに曲がったまま通る）。
 *
 * ここで見ないもの: ソース・レイヤー・地物の状態の記録そのもの（`mapTrace/recordingMap.ts`）。
 */
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { describe, expect, it, vi } from "vitest";

import { Map, Marker, mapOnScreen } from "./maplibre";

const AT = { latitude: 35.7, longitude: 139.7 };

function drawMap(): MapLibreMap {
  const container = document.createElement("div");
  document.body.append(container);
  return new Map({ container, style: "https://tiles.test/style.json", zoom: 13 }) as unknown as MapLibreMap;
}

function line(x: number): GeoJSON.Feature {
  return {
    type: "Feature",
    geometry: {
      type: "LineString",
      coordinates: [
        [x, 0],
        [x, 1],
      ],
    },
    properties: {},
  };
}

describe("maplibre-gl の代役", () => {
  it("押すと、地図全体の購読は押した地点を、レイヤーの購読はそのレイヤーに地物があるときだけその地物を受ける", () => {
    const map = drawMap();
    let underPointer: unknown;
    const onMap = vi.fn((event: { point: unknown }) => {
      underPointer = map.queryRenderedFeatures(event.point as never, { layers: ["bands"] });
    });
    const onRoutes = vi.fn();
    const onBands = vi.fn();
    map.on("click", onMap);
    map.on("click", "routes", onRoutes);
    map.on("click", "bands", onBands);
    map.addLayer({ id: "routes", type: "line", source: "routes" });
    map.addLayer({ id: "bands", type: "line", source: "bands" });

    mapOnScreen().click(AT, [{ layer: "routes", properties: { index: 1 } }]);

    expect(onMap).toHaveBeenCalledWith(expect.objectContaining({ lngLat: { lng: 139.7, lat: 35.7 } }));
    expect(underPointer).toEqual([]);
    expect(onRoutes).toHaveBeenCalledWith(
      expect.objectContaining({
        features: [expect.objectContaining({ layer: { id: "routes" }, properties: { index: 1 } })],
      }),
    );
    expect(onBands).not.toHaveBeenCalled();
    map.remove();
  });

  it("ソースの地物は作ったときの宣言から読め、差し替えれば差し替えた中身になり、スタイルを取り直すと消える", () => {
    const map = drawMap();
    map.addSource("routes", { type: "geojson", data: { type: "FeatureCollection", features: [line(1)] } });
    expect(mapOnScreen().sourceFeatures("routes")).toEqual([line(1)]);

    (map.getSource("routes") as GeoJSONSource).setData({ type: "FeatureCollection", features: [line(2)] });
    expect(mapOnScreen().sourceFeatures("routes")).toEqual([line(2)]);

    map.setStyle("https://tiles.test/style.json?t=1");
    expect(mapOnScreen().sourceFeatures("routes")).toEqual([]);
    expect(mapOnScreen().styles).toEqual(["https://tiles.test/style.json", "https://tiles.test/style.json?t=1"]);
    map.remove();
  });

  it("無い・隠したレイヤーの地物は押せない（MapLibre は押した所に返さない）", () => {
    const map = drawMap();
    map.addLayer({ id: "hidden", type: "line", source: "routes", layout: { visibility: "none" } });

    for (const layer of ["missing", "hidden"]) {
      expect(() => mapOnScreen().click(AT, [{ layer, properties: {} }])).toThrow("描かれていないレイヤー");
    }
    map.remove();
  });

  it("隠したレイヤーは表示中に数えない", () => {
    const map = drawMap();
    map.addLayer({ id: "shown", type: "line", source: "routes" });
    map.addLayer({ id: "hidden", type: "line", source: "routes", layout: { visibility: "none" } });
    expect(mapOnScreen().visibleLayerIds()).toEqual(["shown"]);

    map.setLayoutProperty("hidden", "visibility", "visible");
    expect(mapOnScreen().visibleLayerIds()).toEqual(["shown", "hidden"]);
    map.remove();
  });

  it("印は地図の器へ置かれて画面から引け、外すと消える", () => {
    const map = drawMap();
    const element = document.createElement("div");
    element.setAttribute("aria-label", "目印");
    const marker = new Marker({ element, draggable: true }).setLngLat([139.7, 35.7]).addTo(map as never);

    expect(mapOnScreen().markers()).toEqual([{ coordinates: AT, draggable: true, element }]);
    expect(map.getContainer()).toContainElement(element);

    marker.remove();
    expect(mapOnScreen().markers()).toEqual([]);
    expect(map.getContainer()).not.toContainElement(element);
    map.remove();
  });
});
