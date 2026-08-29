// @vitest-environment node
// DOM/MapLibreを一切使わない純粋関数のみを検証するため、jsdom環境構築コストを省く
// （docs/testing.mdパターン3、windLayer.test.tsと同型）。
import { describe, expect, it } from "vitest";
import {
  mergeWindWayPenalties,
  tilesCoveringViewport,
  windAxisColorExpression,
  WIND_AXIS_FEATURE_STATE_KEY,
  WIND_AXIS_THRESHOLDS,
} from "./windAxisLayer";
import type { MapViewport } from "./windLayer";

describe("windAxisLayer", () => {
  describe("tilesCoveringViewport（改善計画T405: 現在のビューポートを覆う道路タイルの一覧）", () => {
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

  describe("mergeWindWayPenalties（改善計画T405: 複数タイル応答の統合）", () => {
    it("複数タイル分のway_id→wind_penaltyを1つのMapへ統合する", () => {
      const merged = mergeWindWayPenalties([{ "1": 2.5, "2": -1.0 }, { "3": 0.5 }]);

      expect(merged).toEqual(
        new Map([
          [1, 2.5],
          [2, -1.0],
          [3, 0.5],
        ]),
      );
    });

    it("同じway_idが複数タイルに跨って現れた場合は後勝ちにする", () => {
      const merged = mergeWindWayPenalties([{ "1": 1.0 }, { "1": 2.0 }]);
      expect(merged.get(1)).toBe(2.0);
    });

    it("空配列は空のMapを返す", () => {
      expect(mergeWindWayPenalties([])).toEqual(new Map());
    });
  });

  describe("windAxisColorExpression（改善計画T405: setFeatureState値の色分けexpression）", () => {
    it("feature-state未設定（null）の場合はCOLOR_UNKNOWN（不明の灰色）へ分岐するcase式を返す", () => {
      const expression = windAxisColorExpression();
      expect(expression[0]).toBe("case");
      expect(expression[1]).toEqual(["==", ["feature-state", WIND_AXIS_FEATURE_STATE_KEY], null]);
      expect(expression[2]).toBe("#9ca3af"); // axisLayers.ts: COLOR_UNKNOWNと同じ値
    });

    it("段階数はWIND_AXIS_THRESHOLDS.length+1（stepの[しきい値,色]ペア数と一致）", () => {
      const expression = windAxisColorExpression();
      const stepExpression = expression[3] as unknown[];
      expect(stepExpression[0]).toBe("step");
      // step式は ["step", value, color0, threshold1, color1, threshold2, color2, ...] の
      // 並び（MapLibreの仕様: 最初の色は先頭のフォールバック、以降がしきい値・色の対）。
      expect(stepExpression).toHaveLength(3 + WIND_AXIS_THRESHOLDS.length * 2);
    });
  });
});
