// @vitest-environment node
// DOM/MapLibreを一切使わない純粋関数のみを検証するため、jsdom環境構築コストを省く
// （docs/testing.mdパターン3、windLayer.test.tsと同型）。
//
// 改善計画T423（T411の実施）: 旧windAxisLayer.test.ts（現dedicatedWayValueLayer.test.ts）の`tilesCoveringViewport`/
// `mergeWindWayPenalties`（材料非依存のタイル座標計算・複数タイル応答統合）テストを、
// dynamicWayValues.tsへのロジック抽出に合わせてこちらへ移設した。
import { describe, expect, it } from "vitest";
import { mergeDynamicWayValues, tileBoundsLonLat, tilesCoveringViewport } from "./dynamicWayValues";
import type { MapViewport } from "./windLayer";

describe("dynamicWayValues", () => {
  describe("tilesCoveringViewport（現在のビューポートを覆う道路タイルの一覧）", () => {
    it("東京駅付近のビューポートに対し、既知のz14タイル座標を含む結果を返す", () => {
      // MVT_Z, MVT_X, MVT_Y = 14, 14549, 6450（test_road_graph_repository.pyと同じ、
      // NODE1=(35.700, 139.700)付近を含むタイル）に相当する狭いビューポート。
      const viewport: MapViewport = { west: 139.699, south: 35.699, east: 139.701, north: 35.701, zoom: 14 };

      const tiles = tilesCoveringViewport(viewport, 12, 15);

      expect(tiles).toContainEqual({ z: 14, x: 14549, y: 6450 });
    });

    it("ズームをminZoom〜maxZoomへクランプする", () => {
      const lowZoomViewport: MapViewport = { west: 139.6, south: 35.6, east: 139.8, north: 35.8, zoom: 5 };
      const highZoomViewport: MapViewport = { west: 139.699, south: 35.699, east: 139.701, north: 35.701, zoom: 20 };

      const lowZoomTiles = tilesCoveringViewport(lowZoomViewport, 12, 15);
      const highZoomTiles = tilesCoveringViewport(highZoomViewport, 12, 15);

      expect(lowZoomTiles.every((t) => t.z === 12)).toBe(true);
      expect(highZoomTiles.every((t) => t.z === 15)).toBe(true);
    });

    it("ビューポートが1タイルに収まる場合は1件だけ返す", () => {
      const viewport: MapViewport = { west: 139.699, south: 35.699, east: 139.701, north: 35.701, zoom: 14 };
      const tiles = tilesCoveringViewport(viewport, 12, 15);
      expect(tiles).toHaveLength(1);
    });

    it("広いビューポートでは複数タイルを返すが、上限（安全弁）を超えない", () => {
      const wideViewport: MapViewport = { west: 138.5, south: 34.9, east: 140.9, north: 37.1, zoom: 12 };
      const tiles = tilesCoveringViewport(wideViewport, 12, 15);
      expect(tiles.length).toBeGreaterThan(1);
      expect(tiles.length).toBeLessThanOrEqual(64);
    });

    it("同じ入力に対し決定的な結果を返す", () => {
      const viewport: MapViewport = { west: 139.6, south: 35.6, east: 139.8, north: 35.8, zoom: 13 };
      expect(tilesCoveringViewport(viewport, 12, 15)).toEqual(tilesCoveringViewport(viewport, 12, 15));
    });
  });

  describe("mergeDynamicWayValues（複数タイル応答の統合）", () => {
    it("複数タイル分のway_id→値を1つのMapへ統合する", () => {
      const merged = mergeDynamicWayValues([{ "1": 2.5, "2": -1.0 }, { "3": 0.5 }]);

      expect(merged).toEqual(
        new Map([
          [1, 2.5],
          [2, -1.0],
          [3, 0.5],
        ]),
      );
    });

    it("同じway_idが複数タイルに跨って現れた場合は後勝ちにする", () => {
      const merged = mergeDynamicWayValues([{ "1": 1.0 }, { "1": 2.0 }]);
      expect(merged.get(1)).toBe(2.0);
    });

    it("空配列は空のMapを返す", () => {
      expect(mergeDynamicWayValues([])).toEqual(new Map());
    });
  });

  describe("tileBoundsLonLat（改善計画T423: 勾配gridFillのセル境界。backend/app/domain/region.py: tile_bounds_lonlatのJS版）", () => {
    it("既知のz14タイル座標に対し、そのタイルへ含まれるはずの座標を範囲内に含む", () => {
      const bounds = tileBoundsLonLat(14, 14549, 6450);
      expect(bounds.west).toBeLessThanOrEqual(139.7);
      expect(bounds.east).toBeGreaterThanOrEqual(139.7);
      expect(bounds.south).toBeLessThanOrEqual(35.7);
      expect(bounds.north).toBeGreaterThanOrEqual(35.7);
    });

    it("z0タイルは全世界（経度-180〜180）を覆う", () => {
      const bounds = tileBoundsLonLat(0, 0, 0);
      expect(bounds.west).toBeCloseTo(-180, 5);
      expect(bounds.east).toBeCloseTo(180, 5);
    });

    it("同じズームで隣接するタイルは境界を共有する", () => {
      const tileA = tileBoundsLonLat(10, 500, 300);
      const tileB = tileBoundsLonLat(10, 501, 300);
      expect(tileA.east).toBeCloseTo(tileB.west, 9);
    });
  });
});
