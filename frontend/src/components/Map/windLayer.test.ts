import { describe, expect, it } from "vitest";
import {
  clampWindDetailBbox,
  formatWindFrameTime,
  mergeWindGridKeepingStale,
  nearestFrameIndexToNow,
  trimWindGridToCurrentAndFuture,
  windGridToFeatureCollection,
  WIND_SPEED_COLOR_STOPS,
  WIND_SPEED_LEGEND_LEVELS,
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
      {
        latitude: 35.68,
        longitude: 139.77,
        times: ["t0", "t1"],
        wind_speed_ms: [2.5, 3.1],
        wind_direction_deg: [90, 180],
        precipitation_mm: [0, 0],
      },
      {
        latitude: 36.0,
        longitude: 140.0,
        times: ["t0", "t1"],
        wind_speed_ms: [1.0, 4.2],
        wind_direction_deg: [0, 270],
        precipitation_mm: [0, 0],
      },
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

  describe("trimWindGridToCurrentAndFuture（実機フィードバック「過去の風、雨を気にすることはアプリの性質上ない、デフォルト位置を左端に」）", () => {
    const times = ["2026-08-20T00:00", "2026-08-20T01:00", "2026-08-20T02:00", "2026-08-20T03:00"];
    const grid: WindGridPoint[] = [
      {
        latitude: 35.68,
        longitude: 139.77,
        times,
        wind_speed_ms: [1, 2, 3, 4],
        wind_direction_deg: [10, 20, 30, 40],
        precipitation_mm: [0, 0, 0, 0],
      },
      {
        latitude: 36.0,
        longitude: 140.0,
        times,
        wind_speed_ms: [5, 6, 7, 8],
        wind_direction_deg: [50, 60, 70, 80],
        precipitation_mm: [0, 0, 0, 0],
      },
    ];

    it("「現在時刻以下で最も新しい」時刻より前を全格子点・全配列から切り捨てる", () => {
      // 02:30 JSTは02:00(index2)が属する時間帯 -> index2から末尾まで残す
      const result = trimWindGridToCurrentAndFuture(grid, new Date("2026-08-20T02:30:00+09:00"));
      expect(result[0].times).toEqual(["2026-08-20T02:00", "2026-08-20T03:00"]);
      expect(result[0].wind_speed_ms).toEqual([3, 4]);
      expect(result[0].wind_direction_deg).toEqual([30, 40]);
      expect(result[1].wind_speed_ms).toEqual([7, 8]);
    });

    it("正時ちょうどならその時刻から残す（切り上げず現在の時間帯を含める）", () => {
      const result = trimWindGridToCurrentAndFuture(grid, new Date("2026-08-20T02:00:00+09:00"));
      expect(result[0].times).toEqual(["2026-08-20T02:00", "2026-08-20T03:00"]);
    });

    it("空配列を渡すと空配列を返す", () => {
      expect(trimWindGridToCurrentAndFuture([], new Date())).toEqual([]);
    });
  });

  describe("WIND_SPEED_COLOR_STOPS（実機フィードバック「風の色分けをもっと細かくして。ロードバイクで走れない強風域は粒度粗く。微風からそこまでは粒度を細かくして」）", () => {
    // ロードバイクで通常走行できる目安の上限（ビューフォート風力階級6の上限、windLayer.ts
    // のコメント参照）。以降は粒度を粗くする境界。
    const UNRIDEABLE_THRESHOLD_MS = 13.8;

    it("風速は単調増加する", () => {
      for (let i = 1; i < WIND_SPEED_COLOR_STOPS.length; i++) {
        expect(WIND_SPEED_COLOR_STOPS[i].speedMs).toBeGreaterThan(WIND_SPEED_COLOR_STOPS[i - 1].speedMs);
      }
    });

    it("走行可能域（0〜走行困難の境界）は、それ以降の強風域より段の間隔が細かい", () => {
      const rideable = WIND_SPEED_COLOR_STOPS.filter((s) => s.speedMs <= UNRIDEABLE_THRESHOLD_MS);
      const unrideable = WIND_SPEED_COLOR_STOPS.filter((s) => s.speedMs >= UNRIDEABLE_THRESHOLD_MS);
      // 走行可能域には少なくとも5段以上の刻みがある(細かい)
      expect(rideable.length).toBeGreaterThanOrEqual(6);
      const rideableIntervals = rideable.slice(1).map((s, i) => s.speedMs - rideable[i].speedMs);
      const unrideableIntervals = unrideable.slice(1).map((s, i) => s.speedMs - unrideable[i].speedMs);
      const avg = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
      expect(avg(rideableIntervals)).toBeLessThan(avg(unrideableIntervals));
    });
  });

  describe("WIND_SPEED_LEGEND_LEVELS", () => {
    it("走行が難しい強風域は1行にまとめ、走行可能域より粗く見せる", () => {
      const labels = WIND_SPEED_LEGEND_LEVELS.map((l) => l.label);
      expect(labels.some((l) => l.includes("走行が難しい強風域"))).toBe(true);
    });

    it("数値はWIND_SPEED_COLOR_STOPSと食い違わない（単一の情報源）", () => {
      expect(WIND_SPEED_LEGEND_LEVELS[1].color).toBe(WIND_SPEED_COLOR_STOPS[0].color);
      expect(WIND_SPEED_LEGEND_LEVELS.at(-1)?.color).toBe(WIND_SPEED_COLOR_STOPS[6].color);
    });
  });

  describe("mergeWindGridKeepingStale（実機フィードバック「画面端が塗られないことがある」）", () => {
    function point(lat: number, lon: number, speed: number): WindGridPoint {
      return { latitude: lat, longitude: lon, times: ["t0"], wind_speed_ms: [speed], wind_direction_deg: [0], precipitation_mm: [0] };
    }

    it("nextに存在する地点はnextの値を優先する（更新される）", () => {
      const previous = [point(35, 139, 1)];
      const next = [point(35, 139, 9)];
      const result = mergeWindGridKeepingStale(previous, next);
      expect(result).toHaveLength(1);
      expect(result[0].wind_speed_ms).toEqual([9]);
    });

    it("nextに無い地点はpreviousの値のまま残す（一時的な取得失敗で穴を開けない）", () => {
      const previous = [point(35, 139, 1), point(36, 140, 2)];
      const next = [point(35, 139, 9)]; // (36,140)がOpen-Meteo側の失敗で欠落した想定
      const result = mergeWindGridKeepingStale(previous, next);
      expect(result).toHaveLength(2);
      expect(result.find((p) => p.latitude === 36)?.wind_speed_ms).toEqual([2]);
    });

    it("previousが空でもnextだけの結果を返す", () => {
      const next = [point(35, 139, 9)];
      expect(mergeWindGridKeepingStale([], next)).toEqual(next);
    });

    it("nextが空ならpreviousを丸ごと残す", () => {
      const previous = [point(35, 139, 1)];
      expect(mergeWindGridKeepingStale(previous, [])).toEqual(previous);
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
