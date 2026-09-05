// @vitest-environment node
// DOM/MapLibreを一切使わない純粋関数のみを検証するため、jsdom環境構築コストを省く
// （docs/testing.mdパターン3。dynamicWeather.tsはmapLayers.tsを型のみimportしており
// ランタイムのDOM依存が無いことを確認済み）。
import { describe, expect, it } from "vitest";
import {
  CHIP_DYNAMIC_WEATHER_LAYER_IDS,
  DYNAMIC_WEATHER_LAYER_IDS,
  formatDynamicFrameTime,
  frameIndexForTime,
  gridCellRing,
  isWithinFutureWindow,
  mergeFrameTimes,
  nearestTimeIndex,
} from "./dynamicWeather";

describe("dynamicWeather（T183再設計: 動的気象レイヤーの共通契約）", () => {
  describe("mergeFrameTimes", () => {
    it("複数レイヤーのフレーム時刻を昇順・重複排除した1本のタイムラインへ統合する", () => {
      const wind = [{ time: new Date("2026-08-20T12:00:00+09:00") }, { time: new Date("2026-08-20T13:00:00+09:00") }];
      const precip = [{ time: new Date("2026-08-20T12:05:00+09:00") }, { time: new Date("2026-08-20T13:00:00+09:00") }];
      const timeline = mergeFrameTimes([wind, precip]);
      expect(timeline.map((t) => t.toISOString())).toEqual([
        new Date("2026-08-20T12:00:00+09:00").toISOString(),
        new Date("2026-08-20T12:05:00+09:00").toISOString(),
        new Date("2026-08-20T13:00:00+09:00").toISOString(),
      ]);
    });

    it("フレームリストが空、または全体が空なら空配列を返す", () => {
      expect(mergeFrameTimes([])).toEqual([]);
      expect(mergeFrameTimes([[], []])).toEqual([]);
    });
  });

  describe("formatDynamicFrameTime", () => {
    it("JSTで月/日 時:分の形式にする", () => {
      expect(formatDynamicFrameTime(new Date("2026-08-20T12:05:00+09:00"))).toBe("8/20 12:05");
    });

    it("日付をまたぐ時刻も正しく変換する", () => {
      expect(formatDynamicFrameTime(new Date("2026-08-21T06:00:00+09:00"))).toBe("8/21 06:00");
    });
  });

  describe("nearestTimeIndex", () => {
    const times = [new Date("2026-08-20T00:00:00+09:00"), new Date("2026-08-20T03:00:00+09:00"), new Date("2026-08-20T06:00:00+09:00")];

    it("対象時刻に最も近いindexを返す", () => {
      expect(nearestTimeIndex(times, new Date("2026-08-20T04:40:00+09:00"))).toBe(2);
      expect(nearestTimeIndex(times, new Date("2026-08-20T01:00:00+09:00"))).toBe(0);
    });

    it("空配列なら0を返す", () => {
      expect(nearestTimeIndex([], new Date())).toBe(0);
    });
  });

  describe("frameIndexForTime（要件「該当時間データがない場合、地図には描画しない」）", () => {
    const frames = [
      { time: new Date("2026-08-20T12:00:00+09:00") },
      { time: new Date("2026-08-20T13:00:00+09:00") },
      { time: new Date("2026-08-20T14:00:00+09:00") },
    ];

    it("データ範囲内の時刻には最も近いフレームのindexを返す", () => {
      expect(frameIndexForTime(frames, new Date("2026-08-20T12:40:00+09:00"))).toBe(1);
    });

    it("データ範囲より前・後の時刻はnull（描画しない）を返す(従来のクランプ挙動は廃止)", () => {
      expect(frameIndexForTime(frames, new Date("2026-08-20T00:00:00+09:00"))).toBeNull();
      expect(frameIndexForTime(frames, new Date("2026-08-21T00:00:00+09:00"))).toBeNull();
    });

    it("境界ちょうどの時刻は範囲内として扱う", () => {
      expect(frameIndexForTime(frames, new Date("2026-08-20T12:00:00+09:00"))).toBe(0);
      expect(frameIndexForTime(frames, new Date("2026-08-20T14:00:00+09:00"))).toBe(2);
    });

    it("フレームが空ならnullを返す", () => {
      expect(frameIndexForTime([], new Date())).toBeNull();
    });
  });

  describe("gridCellRing（gridFill表現のセルジオメトリ）", () => {
    it("格子点を中心とする1辺spacingDegの閉じた正方形リングを返す", () => {
      const ring = gridCellRing(35.68, 139.77, 0.1);
      expect(ring).toHaveLength(5);
      const [minLon, minLat] = ring[0];
      const [maxLon, maxLat] = ring[2];
      expect(minLon).toBeCloseTo(139.72);
      expect(minLat).toBeCloseTo(35.63);
      expect(maxLon).toBeCloseTo(139.82);
      expect(maxLat).toBeCloseTo(35.73);
      expect(ring[0]).toEqual(ring[ring.length - 1]);
    });
  });

  describe("isWithinFutureWindow（改善計画T432、線状降水帯予測マップの表示時間窓判定）", () => {
    const now = new Date("2026-08-30T12:00:00+09:00");
    const windowMs = 3 * 60 * 60 * 1000;

    it("現在時刻ちょうどは範囲内", () => {
      expect(isWithinFutureWindow(now, now, windowMs)).toBe(true);
    });

    it("時間窓の範囲内（例: 2時間59分先）は範囲内", () => {
      const target = new Date(now.getTime() + windowMs - 60 * 1000);
      expect(isWithinFutureWindow(target, now, windowMs)).toBe(true);
    });

    it("時間窓ちょうど（3時間先）は範囲内", () => {
      const target = new Date(now.getTime() + windowMs);
      expect(isWithinFutureWindow(target, now, windowMs)).toBe(true);
    });

    it("時間窓を超えた未来（3時間1分先）は範囲外", () => {
      const target = new Date(now.getTime() + windowMs + 60 * 1000);
      expect(isWithinFutureWindow(target, now, windowMs)).toBe(false);
    });

    it("過去（現在より前）は範囲外", () => {
      const target = new Date(now.getTime() - 60 * 1000);
      expect(isWithinFutureWindow(target, now, windowMs)).toBe(false);
    });
  });

  describe("CHIP_DYNAMIC_WEATHER_LAYER_IDS（改善計画T606: キキクル4種のチップ化）", () => {
    it("キキクル4種を含む（他の環境グループ気象レイヤーと同じチップ付き扱い）", () => {
      expect(CHIP_DYNAMIC_WEATHER_LAYER_IDS).toContain("landslideRisk");
      expect(CHIP_DYNAMIC_WEATHER_LAYER_IDS).toContain("heavyRainRisk");
      expect(CHIP_DYNAMIC_WEATHER_LAYER_IDS).toContain("inundationRisk");
      expect(CHIP_DYNAMIC_WEATHER_LAYER_IDS).toContain("floodRisk");
    });

    it("DYNAMIC_WEATHER_LAYER_IDSはCHIP_DYNAMIC_WEATHER_LAYER_IDSと同じ（常時マウント・チップ無しの要素を持たない）", () => {
      expect(DYNAMIC_WEATHER_LAYER_IDS).toEqual(CHIP_DYNAMIC_WEATHER_LAYER_IDS);
    });
  });
});
