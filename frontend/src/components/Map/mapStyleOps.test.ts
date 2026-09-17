// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  areaLayerAnchor,
  areaLayerAnchorId,
  basemapAreaLayersAfter,
  isAreaLayerType,
  prepareBasemapForAreaLayers,
  resetBasemapAreaLayerPreparation,
} from "@/components/Map/mapStyleOps";

// 基礎地図（OpenFreeMap liberty、`/api/basemap/styles/liberty`が中継するもの）の実際の
// レイヤー並び。種別・source-layer・idだけを写している。差し込み位置の根拠はここに並ぶ
// idでも並び順でもなく、ベクタタイルのスキーマ（OpenMapTiles）が道路網に付けている名前
// `transportation`である。このフィクスチャは、その名前で実物の道路網が全部拾えること
// （トンネルも橋も含む）を固定するために置く。
const LIBERTY_LAYERS = `
background - background
raster - natural_earth
fill park park
line park park_outline
fill landuse landuse_residential
fill landcover landcover_wood
fill landcover landcover_grass
fill landcover landcover_ice
fill landcover landcover_wetland
fill landuse landuse_pitch
fill landuse landuse_track
fill landuse landuse_cemetery
fill landuse landuse_hospital
fill landuse landuse_school
line waterway waterway_tunnel
line waterway waterway_river
line waterway waterway_other
fill water water
fill landcover landcover_sand
fill aeroway aeroway_fill
line aeroway aeroway_runway
line aeroway aeroway_taxiway
line transportation tunnel_motorway_link_casing
line transportation tunnel_service_track_casing
line transportation tunnel_link_casing
line transportation tunnel_street_casing
line transportation tunnel_secondary_tertiary_casing
line transportation tunnel_trunk_primary_casing
line transportation tunnel_motorway_casing
line transportation tunnel_path_pedestrian
line transportation tunnel_motorway_link
line transportation tunnel_service_track
line transportation tunnel_link
line transportation tunnel_minor
line transportation tunnel_secondary_tertiary
line transportation tunnel_trunk_primary
line transportation tunnel_motorway
line transportation tunnel_major_rail
line transportation tunnel_major_rail_hatching
line transportation tunnel_transit_rail
line transportation tunnel_transit_rail_hatching
fill transportation road_area_pattern
line transportation road_motorway_link_casing
line transportation road_service_track_casing
line transportation road_link_casing
line transportation road_minor_casing
line transportation road_secondary_tertiary_casing
line transportation road_trunk_primary_casing
line transportation road_motorway_casing
line transportation road_path_pedestrian
line transportation road_motorway_link
line transportation road_service_track
line transportation road_link
line transportation road_minor
line transportation road_secondary_tertiary
line transportation road_trunk_primary
line transportation road_motorway
line transportation road_major_rail
line transportation road_major_rail_hatching
line transportation road_transit_rail
line transportation road_transit_rail_hatching
symbol transportation road_one_way_arrow
symbol transportation road_one_way_arrow_opposite
line transportation bridge_motorway_link_casing
line transportation bridge_service_track_casing
line transportation bridge_link_casing
line transportation bridge_street_casing
line transportation bridge_path_pedestrian_casing
line transportation bridge_secondary_tertiary_casing
line transportation bridge_trunk_primary_casing
line transportation bridge_motorway_casing
line transportation bridge_path_pedestrian
line transportation bridge_motorway_link
line transportation bridge_service_track
line transportation bridge_link
line transportation bridge_street
line transportation bridge_secondary_tertiary
line transportation bridge_trunk_primary
line transportation bridge_motorway
line transportation bridge_major_rail
line transportation bridge_major_rail_hatching
line transportation bridge_transit_rail
line transportation bridge_transit_rail_hatching
fill building building
fill-extrusion building building-3d
line boundary boundary_3
line boundary boundary_2
line boundary boundary_disputed
symbol waterway waterway_line_label
symbol water_name water_name_point_label
symbol water_name water_name_line_label
symbol poi poi_r20
symbol poi poi_r7
symbol poi poi_r1
symbol poi poi_transit
symbol transportation_name highway-name-path
symbol transportation_name highway-name-minor
symbol transportation_name highway-name-major
symbol transportation_name highway-shield-non-us
symbol transportation_name highway-shield-us-interstate
symbol transportation_name road_shield_us
symbol aerodrome_label airport
symbol place label_other
symbol place label_village
symbol place label_town
symbol place label_state
symbol place label_city
symbol place label_city_capital
symbol place label_country_3
symbol place label_country_2
symbol place label_country_1
`
  .trim()
  .split("\n")
  .map((line) => {
    const [type, sourceLayer, id] = line.split(" ");
    return sourceLayer === "-" ? { id, type } : { id, type, "source-layer": sourceLayer };
  });

describe("areaLayerAnchorId（面レイヤーの差し込み位置）", () => {
  it("実物の基礎地図では、道路網の最初のレイヤー（トンネルの一番下）を返す", () => {
    expect(areaLayerAnchorId(LIBERTY_LAYERS)).toBe("tunnel_motorway_link_casing");
  });

  // トンネルより後ろを指すと、道路網がトンネル区間だけ面の下に沈んで道が途切れて見える
  // （実機で「道も途切れているものがあって、主要道と細かい道の間に色が差し込まれてない？」）。
  it("位置は地上の道路より前（トンネル区間が面の下に残らない）", () => {
    const anchorIndex = LIBERTY_LAYERS.findIndex((l) => l.id === areaLayerAnchorId(LIBERTY_LAYERS));
    const roadNetwork = LIBERTY_LAYERS.map((l, i) => ({ ...l, i })).filter(
      (l) => l["source-layer"] === "transportation",
    );
    expect(roadNetwork.length).toBeGreaterThan(40);
    expect(roadNetwork.every((l) => l.i >= anchorIndex)).toBe(true);
  });

  it("土地の塗り（公園・土地利用・水面・空港）は位置より前＝面の下に残る", () => {
    const anchorIndex = LIBERTY_LAYERS.findIndex((l) => l.id === areaLayerAnchorId(LIBERTY_LAYERS));
    for (const id of ["park", "landuse_residential", "landcover_wood", "water", "aeroway_fill"]) {
      expect(LIBERTY_LAYERS.findIndex((l) => l.id === id)).toBeLessThan(anchorIndex);
    }
  });

  it("道路網を持たないスタイルではundefined（差し込み先が無く最前面になる）", () => {
    expect(areaLayerAnchorId([{ id: "background" }])).toBeUndefined();
    expect(areaLayerAnchorId([])).toBeUndefined();
  });
});

describe("basemapAreaLayersAfter（差し込み位置より後ろの面）", () => {
  it("実物の基礎地図では、歩行者area・建物が道路網より後ろに残る（これを前へ動かす）", () => {
    expect(basemapAreaLayersAfter(LIBERTY_LAYERS, "tunnel_motorway_link_casing")).toEqual([
      "road_area_pattern",
      "building",
      "building-3d",
    ]);
  });

  it("差し込み位置が並びに無ければ空（動かす対象を取り違えない）", () => {
    expect(basemapAreaLayersAfter(LIBERTY_LAYERS, "存在しないレイヤー")).toEqual([]);
  });
});

describe("isAreaLayerType（面で塗る種別か）", () => {
  it("下を隠す描き方は面、上に乗って読まれる描き方は面ではない", () => {
    expect(["raster", "fill", "fill-extrusion", "background", "hillshade"].every(isAreaLayerType)).toBe(true);
    expect(["line", "symbol", "circle", "heatmap"].some(isAreaLayerType)).toBe(false);
  });
});

describe("prepareBasemapForAreaLayers（基礎地図を面レイヤー用に整える）", () => {
  function fakeMap(layers: { id: string; type?: string; "source-layer"?: string }[]) {
    const moveCalls: { layerId: string; beforeId?: string }[] = [];
    return {
      moveCalls,
      getStyle: () => ({ layers }),
      getLayer: (id: string) => (layers.some((l) => l.id === id) ? {} : undefined),
      moveLayer: (layerId: string, beforeId?: string) => moveCalls.push({ layerId, beforeId }),
    };
  }

  it("道路網より後ろの面を道路網の手前へ動かし、差し込み位置を記録する", () => {
    const map = fakeMap([...LIBERTY_LAYERS]);

    prepareBasemapForAreaLayers(map as never);

    expect(map.moveCalls).toEqual([
      { layerId: "road_area_pattern", beforeId: "tunnel_motorway_link_casing" },
      { layerId: "building", beforeId: "tunnel_motorway_link_casing" },
      { layerId: "building-3d", beforeId: "tunnel_motorway_link_casing" },
    ]);
    expect(areaLayerAnchor(map as never)).toBe("tunnel_motorway_link_casing");
  });

  it("同じスタイルに対しては1度しか走らない（後から呼んでも並びを触らない）", () => {
    const map = fakeMap([...LIBERTY_LAYERS]);

    prepareBasemapForAreaLayers(map as never);
    prepareBasemapForAreaLayers(map as never);

    expect(map.moveCalls).toHaveLength(3);
  });

  it("スタイルを差し替えたら、新しい並びに対して改めて走る", () => {
    const map = fakeMap([...LIBERTY_LAYERS]);
    prepareBasemapForAreaLayers(map as never);

    resetBasemapAreaLayerPreparation(map as never);
    prepareBasemapForAreaLayers(map as never);

    expect(map.moveCalls).toHaveLength(6);
  });

  it("道路網を持たないスタイルでは何も動かさず、差し込み位置も持たない", () => {
    const map = fakeMap([{ id: "background", type: "background" }]);

    prepareBasemapForAreaLayers(map as never);

    expect(map.moveCalls).toEqual([]);
    expect(areaLayerAnchor(map as never)).toBeUndefined();
  });
});
