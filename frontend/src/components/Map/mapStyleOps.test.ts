// @vitest-environment node
import { describe, expect, it } from "vitest";
import { areaLayerAnchorId, isAreaLayerType } from "@/components/Map/mapStyleOps";

// 面（土地被覆・水域・建物）の上、線・記号（道路・境界・地名）の下という位置を、
// 基礎地図のレイヤーidを名指しせずスタイルの並びから導けることを固定する。
describe("areaLayerAnchorId（面レイヤーの差し込み位置）", () => {
  const basemapLike = [
    { id: "background", type: "background" },
    { id: "landuse", type: "fill" },
    { id: "waterway", type: "line" },
    { id: "water", type: "fill" },
    { id: "building", type: "fill" },
    { id: "road_motorway", type: "line" },
    { id: "place_label", type: "symbol" },
  ];

  it("最後の面レイヤーの次を返す（途中に線があっても、その後ろの面に追い越される）", () => {
    expect(areaLayerAnchorId(basemapLike)).toBe("road_motorway");
  });

  it("面しか無いスタイルではundefined（差し込み先が無く最前面になる）", () => {
    expect(areaLayerAnchorId([{ id: "background", type: "background" }])).toBeUndefined();
  });

  it("空のスタイルでもundefinedを返す（例外にしない）", () => {
    expect(areaLayerAnchorId([])).toBeUndefined();
  });
});

describe("isAreaLayerType（面で塗る種別か）", () => {
  it("下を隠す描き方は面、上に乗って読まれる描き方は面ではない", () => {
    expect(["raster", "fill", "fill-extrusion", "background", "hillshade"].every(isAreaLayerType)).toBe(true);
    expect(["line", "symbol", "circle", "heatmap"].some(isAreaLayerType)).toBe(false);
  });
});
