import { describe, expect, it } from "vitest";
import {
  clampWindDetailBbox,
  formatWindFrameTime,
  nearestFrameIndexToNow,
  windGridToCellFeatureCollection,
  windGridToFeatureCollection,
} from "./windLayer";
import type { WindGridPoint } from "@/types/weather";

describe("windLayer", () => {
  describe("nearestFrameIndexToNow", () => {
    const times = ["2026-08-20T00:00", "2026-08-20T03:00", "2026-08-20T06:00"];

    it("現在時刻(JST)に最も近いフレームのindexを返す", () => {
      // 2026-08-20T04:40 JST = 04:40+09:00 は 03:00寄り(index1)より06:00寄り(index2)
      expect(nearestFrameIndexToNow(times, new Date("2026-08-20T04:40:00+09:00"))).toBe(2);
      expect(nearestFrameIndexToNow(times, new Date("2026-08-20T01:00:00+09:00"))).toBe(0);
    });

    it("空配列なら0を返す", () => {
      expect(nearestFrameIndexToNow([], new Date())).toBe(0);
    });
  });

  describe("formatWindFrameTime", () => {
    it("JST時刻文字列を日付・時刻表示へ変換する", () => {
      expect(formatWindFrameTime("2026-08-20T12:00")).toBe("8/20 12:00");
    });

    it("日付をまたぐ時刻も正しく変換する", () => {
      expect(formatWindFrameTime("2026-08-21T06:00")).toBe("8/21 06:00");
    });

    it("オフセット無し表記をJSTとして解釈する(ブラウザのローカルタイムゾーンに依存しない)", () => {
      // +09:00を明示せずDateへ渡すとブラウザのローカルタイムゾーンとして解釈されてしまうため、
      // parseJstTime内部で明示的に付与していることを確認する回帰テスト。
      const result = formatWindFrameTime("2026-08-20T00:00");
      expect(result).toBe("8/20 00:00");
    });
  });

  describe("windGridToFeatureCollection", () => {
    const grid: WindGridPoint[] = [
      { latitude: 35.68, longitude: 139.77, times: ["t0", "t1"], wind_speed_ms: [2.5, 3.1], wind_direction_deg: [90, 180] },
      { latitude: 36.0, longitude: 140.0, times: ["t0", "t1"], wind_speed_ms: [1.0, 4.2], wind_direction_deg: [0, 270] },
    ];

    it("指定フレームの値でGeoJSON FeatureCollectionを構築する", () => {
      const fc = windGridToFeatureCollection(grid, 0);
      expect(fc.type).toBe("FeatureCollection");
      expect(fc.features).toHaveLength(2);
      expect(fc.features[0].geometry.coordinates).toEqual([139.77, 35.68]);
      expect(fc.features[0].properties.speed).toBe(2.5);
      // bearing = (direction + 180) % 360（風が吹いていく方向）
      expect(fc.features[0].properties.bearing).toBe(270);
      expect(fc.features[1].properties.bearing).toBe(180);
    });

    it("フレームが変わると値も追従する", () => {
      const fc = windGridToFeatureCollection(grid, 1);
      expect(fc.features[0].properties.speed).toBe(3.1);
      expect(fc.features[1].properties.speed).toBe(4.2);
    });

    it("frameIndexが範囲外の格子点はスキップする(欠損に頑健)", () => {
      const fc = windGridToFeatureCollection(grid, 5);
      expect(fc.features).toHaveLength(0);
    });

    it("空配列を渡すと空のFeatureCollectionを返す", () => {
      const fc = windGridToFeatureCollection([], 0);
      expect(fc.features).toHaveLength(0);
    });
  });

  describe("windGridToCellFeatureCollection", () => {
    const grid: WindGridPoint[] = [
      { latitude: 35.68, longitude: 139.77, times: ["t0", "t1"], wind_speed_ms: [2.5, 3.1], wind_direction_deg: [90, 180] },
      { latitude: 36.0, longitude: 140.0, times: ["t0", "t1"], wind_speed_ms: [1.0, 4.2], wind_direction_deg: [0, 270] },
    ];

    it("各点を中心とする1辺spacingDegの正方形ポリゴンを作る", () => {
      const fc = windGridToCellFeatureCollection(grid, 0, 0.1);
      expect(fc.features).toHaveLength(2);
      const [ring] = fc.features[0].geometry.coordinates;
      // 中心(139.77, 35.68)を囲む1辺0.1度の正方形(閉じたリングで5点)
      expect(ring).toHaveLength(5);
      expect(ring[0][0]).toBeCloseTo(139.72);
      expect(ring[0][1]).toBeCloseTo(35.63);
      expect(ring[2][0]).toBeCloseTo(139.82);
      expect(ring[2][1]).toBeCloseTo(35.73);
      expect(fc.features[0].properties.speed).toBe(2.5);
    });

    it("frameIndexが変わると値も追従する", () => {
      const fc = windGridToCellFeatureCollection(grid, 1, 0.1);
      expect(fc.features[0].properties.speed).toBe(3.1);
      expect(fc.features[1].properties.speed).toBe(4.2);
    });

    it("速度が欠損している格子点はスキップする", () => {
      const sparse: WindGridPoint[] = [
        { latitude: 35.68, longitude: 139.77, times: ["t0"], wind_speed_ms: [null as unknown as number], wind_direction_deg: [90] },
      ];
      const fc = windGridToCellFeatureCollection(sparse, 0, 0.1);
      expect(fc.features).toHaveLength(0);
    });

    it("空配列を渡すと空のFeatureCollectionを返す", () => {
      const fc = windGridToCellFeatureCollection([], 0, 0.1);
      expect(fc.features).toHaveLength(0);
    });
  });

  describe("clampWindDetailBbox", () => {
    it("クリップ幅より狭いビューポートはそのまま返す", () => {
      const bbox = clampWindDetailBbox({ west: 139.7, south: 35.6, east: 139.8, north: 35.7, zoom: 13 });
      expect(bbox).toEqual({ minLon: 139.7, minLat: 35.6, maxLon: 139.8, maxLat: 35.7 });
    });

    it("クリップ幅より広いビューポートは中心を基準に0.5度四方へクリップする", () => {
      // 経度方向に3度と広いビューポート(横長デスクトップ・低ズーム相当)
      const bbox = clampWindDetailBbox({ west: 138.0, south: 35.5, east: 141.0, north: 35.7, zoom: 10 });
      const centerLon = (138.0 + 141.0) / 2;
      expect(bbox.minLon).toBeCloseTo(centerLon - 0.25);
      expect(bbox.maxLon).toBeCloseTo(centerLon + 0.25);
      expect(bbox.maxLon - bbox.minLon).toBeCloseTo(0.5);
    });

    it("クリップ後もビューポートの範囲内に収まる(ビューポートより外側へはみ出さない)", () => {
      const viewport = { west: 139.0, south: 35.0, east: 140.0, north: 36.0, zoom: 8 };
      const bbox = clampWindDetailBbox(viewport);
      expect(bbox.minLon).toBeGreaterThanOrEqual(viewport.west);
      expect(bbox.maxLon).toBeLessThanOrEqual(viewport.east);
      expect(bbox.minLat).toBeGreaterThanOrEqual(viewport.south);
      expect(bbox.maxLat).toBeLessThanOrEqual(viewport.north);
    });
  });
});
