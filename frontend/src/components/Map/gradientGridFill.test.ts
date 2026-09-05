// @vitest-environment node
// DOM/MapLibreを一切使わない純粋関数のみを検証するため、jsdom環境構築コストを省く。
import { describe, expect, it } from "vitest";
import { gradientFillColorExpression, gradientGridCellsFromTileResponses } from "./gradientGridFill";
import { COLOR_LOADING, COLOR_NO_DATA } from "./valueScale";
import type { TileDynamicWayValues } from "@/hooks/useDynamicWayValues";

describe("gradientGridFill（改善計画T423: 環境グループの勾配面表示）", () => {
  describe("gradientGridCellsFromTileResponses", () => {
    it("タイルごとのway値を平均し、タイル境界を1セルとするFeatureCollectionを作る", () => {
      const byTile: TileDynamicWayValues[] = [
        { tile: { z: 14, x: 14549, y: 6450 }, values: { "1": 4.0, "2": 2.0 } },
      ];

      const result = gradientGridCellsFromTileResponses(byTile);

      expect(result.type).toBe("FeatureCollection");
      expect(result.features).toHaveLength(1);
      expect(result.features[0].properties.gradientValue).toBe(3.0);
      expect(result.features[0].geometry.type).toBe("Polygon");
      // 閉じた矩形（5点、最初と最後が一致）。
      const ring = result.features[0].geometry.coordinates[0];
      expect(ring).toHaveLength(5);
      expect(ring[0]).toEqual(ring[4]);
    });

    it("値が1件も無いタイル（空応答）はセルに含めない", () => {
      const byTile: TileDynamicWayValues[] = [
        { tile: { z: 14, x: 14549, y: 6450 }, values: {} },
        { tile: { z: 14, x: 14550, y: 6450 }, values: { "3": 1.0 } },
      ];

      const result = gradientGridCellsFromTileResponses(byTile);

      expect(result.features).toHaveLength(1);
      expect(result.features[0].properties.gradientValue).toBe(1.0);
    });

    it("複数タイルはそれぞれ独立したセルになる", () => {
      const byTile: TileDynamicWayValues[] = [
        { tile: { z: 14, x: 14549, y: 6450 }, values: { "1": 5.0 } },
        { tile: { z: 14, x: 14550, y: 6450 }, values: { "2": -5.0 } },
      ];

      const result = gradientGridCellsFromTileResponses(byTile);

      expect(result.features).toHaveLength(2);
    });

    it("空配列は空のFeatureCollectionを返す", () => {
      expect(gradientGridCellsFromTileResponses([])).toEqual({ type: "FeatureCollection", features: [] });
    });
  });

  describe("gradientFillColorExpression", () => {
    it('["get","gradientValue"]を値取得式に使ったcase式を返す', () => {
      const expression = gradientFillColorExpression();
      expect(expression[1]).toEqual(["==", ["get", "gradientValue"], null]);
    });

    it("loading省略時・falseはCOLOR_NO_DATA、trueはCOLOR_LOADINGへ倒す（改善計画T607）", () => {
      expect(gradientFillColorExpression()[2]).toBe(COLOR_NO_DATA);
      expect(gradientFillColorExpression(undefined, false)[2]).toBe(COLOR_NO_DATA);
      expect(gradientFillColorExpression(undefined, true)[2]).toBe(COLOR_LOADING);
    });
  });
});
