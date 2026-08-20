import { describe, expect, it } from "vitest";
import { formatWindFrameTime, nearestFrameIndexToNow, windGridToFeatureCollection } from "./windLayer";
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
});
