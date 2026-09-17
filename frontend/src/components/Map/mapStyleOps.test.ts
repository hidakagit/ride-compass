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
// レイヤーの並び。種別とidだけを写している。**導出の根拠は「道路網は最も長い線の連なりに
// なる」という並びの性質で、ここに並ぶidそのものではない**——このフィクスチャは、その性質が
// 実物で成り立っていることを固定するためのもので、配信元が並びを変えれば実物とはずれる。
// ずれたことは実行時のログ（map:lifecycle「面レイヤーの差し込み位置」）で分かる。
const LIBERTY_LAYERS = `
background background
raster natural_earth
fill park
line park_outline
fill landuse_residential
fill landcover_wood
fill landcover_grass
fill landcover_ice
fill landcover_wetland
fill landuse_pitch
fill landuse_track
fill landuse_cemetery
fill landuse_hospital
fill landuse_school
line waterway_tunnel
line waterway_river
line waterway_other
fill water
fill landcover_sand
fill aeroway_fill
line aeroway_runway
line aeroway_taxiway
line tunnel_motorway_link_casing
line tunnel_service_track_casing
line tunnel_link_casing
line tunnel_street_casing
line tunnel_secondary_tertiary_casing
line tunnel_trunk_primary_casing
line tunnel_motorway_casing
line tunnel_path_pedestrian
line tunnel_motorway_link
line tunnel_service_track
line tunnel_link
line tunnel_minor
line tunnel_secondary_tertiary
line tunnel_trunk_primary
line tunnel_motorway
line tunnel_major_rail
line tunnel_major_rail_hatching
line tunnel_transit_rail
line tunnel_transit_rail_hatching
fill road_area_pattern
line road_motorway_link_casing
line road_service_track_casing
line road_link_casing
line road_minor_casing
line road_secondary_tertiary_casing
line road_trunk_primary_casing
line road_motorway_casing
line road_path_pedestrian
line road_motorway_link
line road_service_track
line road_link
line road_minor
line road_secondary_tertiary
line road_trunk_primary
line road_motorway
line road_major_rail
line road_major_rail_hatching
line road_transit_rail
line road_transit_rail_hatching
symbol road_one_way_arrow
symbol road_one_way_arrow_opposite
line bridge_motorway_link_casing
line bridge_service_track_casing
line bridge_link_casing
line bridge_street_casing
line bridge_path_pedestrian_casing
line bridge_secondary_tertiary_casing
line bridge_trunk_primary_casing
line bridge_motorway_casing
line bridge_path_pedestrian
line bridge_motorway_link
line bridge_service_track
line bridge_link
line bridge_street
line bridge_secondary_tertiary
line bridge_trunk_primary
line bridge_motorway
line bridge_major_rail
line bridge_major_rail_hatching
line bridge_transit_rail
line bridge_transit_rail_hatching
fill building
fill-extrusion building-3d
line boundary_3
line boundary_2
line boundary_disputed
symbol waterway_line_label
symbol water_name_point_label
symbol water_name_line_label
symbol poi_r20
symbol poi_r7
symbol poi_r1
symbol poi_transit
symbol highway-name-path
symbol highway-name-minor
symbol highway-name-major
symbol highway-shield-non-us
symbol highway-shield-us-interstate
symbol road_shield_us
symbol airport
symbol label_other
symbol label_village
symbol label_town
symbol label_state
symbol label_city
symbol label_city_capital
symbol label_country_3
symbol label_country_2
symbol label_country_1
`
  .trim()
  .split("\n")
  .map((line) => {
    const [type, id] = line.split(" ");
    return { id, type };
  });

describe("areaLayerAnchorId（面レイヤーの差し込み位置）", () => {
  it("実物の基礎地図では、道路網の先頭（tunnel/bridgeを含む最長の線の連なり）を返す", () => {
    expect(areaLayerAnchorId(LIBERTY_LAYERS)).toBe("road_motorway_link_casing");
  });

  it("実物の基礎地図では、道路より後ろに残る面は建物だけになる（これを前へ動かす）", () => {
    expect(basemapAreaLayersAfter(LIBERTY_LAYERS, "road_motorway_link_casing")).toEqual(["building", "building-3d"]);
  });

  // 「最後に面を描いたレイヤーの次」を採ると道路の後ろまで下がってしまうこと自体を固定する
  // （実機で`boundary_3`が返り、面が道路を覆ったまま残っていた）。
  it("最後の面の次は道路より後ろ（この位置では面が道路を覆う）", () => {
    const lastArea = LIBERTY_LAYERS.map((l) => l.type).reduce((acc, t, i) => (isAreaLayerType(t) ? i : acc), -1);
    expect(LIBERTY_LAYERS[lastArea].id).toBe("building-3d");
    expect(LIBERTY_LAYERS[lastArea + 1].id).toBe("boundary_3");
  });

  it("線・記号を持たないスタイルではundefined（差し込み先が無く最前面になる）", () => {
    expect(areaLayerAnchorId([{ id: "background", type: "background" }])).toBeUndefined();
    expect(areaLayerAnchorId([])).toBeUndefined();
  });

  it("連なりが同じ長さなら先に現れた方を採る（後ろのものへ滑らない）", () => {
    const layers = [
      { id: "bg", type: "background" },
      { id: "a1", type: "line" },
      { id: "a2", type: "line" },
      { id: "f", type: "fill" },
      { id: "b1", type: "line" },
      { id: "b2", type: "line" },
    ];
    expect(areaLayerAnchorId(layers)).toBe("a1");
  });
});

describe("basemapAreaLayersAfter（差し込み位置より後ろの面）", () => {
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
  function fakeMap(layers: { id: string; type: string }[]) {
    const moveCalls: { layerId: string; beforeId?: string }[] = [];
    return {
      moveCalls,
      getStyle: () => ({ layers }),
      getLayer: (id: string) => (layers.some((l) => l.id === id) ? {} : undefined),
      moveLayer: (layerId: string, beforeId?: string) => moveCalls.push({ layerId, beforeId }),
    };
  }

  it("道路より後ろの面を道路の手前へ動かし、差し込み位置を記録する", () => {
    const map = fakeMap([...LIBERTY_LAYERS]);

    prepareBasemapForAreaLayers(map as never);

    expect(map.moveCalls).toEqual([
      { layerId: "building", beforeId: "road_motorway_link_casing" },
      { layerId: "building-3d", beforeId: "road_motorway_link_casing" },
    ]);
    expect(areaLayerAnchor(map as never)).toBe("road_motorway_link_casing");
  });

  it("同じスタイルに対しては1度しか走らない（後から呼んでも並びを触らない）", () => {
    const map = fakeMap([...LIBERTY_LAYERS]);

    prepareBasemapForAreaLayers(map as never);
    prepareBasemapForAreaLayers(map as never);

    expect(map.moveCalls).toHaveLength(2);
  });

  it("スタイルを差し替えたら、新しい並びに対して改めて走る", () => {
    const map = fakeMap([...LIBERTY_LAYERS]);
    prepareBasemapForAreaLayers(map as never);

    resetBasemapAreaLayerPreparation(map as never);
    prepareBasemapForAreaLayers(map as never);

    expect(map.moveCalls).toHaveLength(4);
  });

  it("線・記号を持たないスタイルでは何も動かさず、差し込み位置も持たない", () => {
    const map = fakeMap([{ id: "background", type: "background" }]);

    prepareBasemapForAreaLayers(map as never);

    expect(map.moveCalls).toEqual([]);
    expect(areaLayerAnchor(map as never)).toBeUndefined();
  });
});
