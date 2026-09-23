// @vitest-environment node
import { describe, expect, it } from "vitest";

import { mergeDynamicWayValues, tileContainingLonLat, tilesCoveringViewport } from "./dynamicWayValues";

describe("tileContainingLonLat（1点を含む道路タイル）", () => {
  it("地図のズームを切り捨て、タイルがあるズームの範囲へ収めてから引く", () => {
    // 東京駅付近。z14では 14552/6451
    expect(tileContainingLonLat(139.767, 35.681, 14.8, 12, 16)).toEqual({ z: 14, x: 14552, y: 6451 });
    expect(tileContainingLonLat(139.767, 35.681, 18, 12, 16).z).toBe(16);
    expect(tileContainingLonLat(139.767, 35.681, 5, 12, 16).z).toBe(12);
  });

  it("端（経度180度・メルカトルの極）でもタイル番号の範囲を出ない", () => {
    expect(tileContainingLonLat(180, 89.9, 2, 0, 20)).toEqual({ z: 2, x: 3, y: 0 });
    expect(tileContainingLonLat(-180, -89.9, 2, 0, 20)).toEqual({ z: 2, x: 0, y: 3 });
  });
});

describe("tilesCoveringViewport（画面を覆う道路タイル）", () => {
  it("北西の角から南東の角までの矩形のタイルを、1点を引くときと同じズームで並べる", () => {
    const viewport = { west: 139.75, north: 35.69, east: 139.78, south: 35.67, zoom: 14.2 };
    const tiles = tilesCoveringViewport(viewport, 12, 16);
    const nw = tileContainingLonLat(viewport.west, viewport.north, viewport.zoom, 12, 16);
    const se = tileContainingLonLat(viewport.east, viewport.south, viewport.zoom, 12, 16);
    expect(tiles).toHaveLength((se.x - nw.x + 1) * (se.y - nw.y + 1));
    expect(tiles[0]).toEqual(nw);
    expect(tiles.at(-1)).toEqual(se);
  });

  it("極端に広い画面でも1回に引くタイルは64枚まで", () => {
    const tiles = tilesCoveringViewport({ west: 120, north: 46, east: 150, south: 24, zoom: 12 }, 12, 16);
    expect(tiles).toHaveLength(64);
  });
});

describe("mergeDynamicWayValues（複数タイルの値を1つへ）", () => {
  it("鍵は文字列のまま（edge_idは数値ではない）、同じ鍵は後の応答で上書きする", () => {
    const merged = mergeDynamicWayValues([{ "123": 1, "e:4-5": 2 }, { "123": 3 }]);
    expect([...merged]).toEqual([
      ["123", 3],
      ["e:4-5", 2],
    ]);
  });
});
