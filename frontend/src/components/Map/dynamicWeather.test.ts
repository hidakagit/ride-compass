// @vitest-environment node
// DOM/MapLibreを一切使わない純粋関数のみを検証するため、jsdom環境構築コストを省く
// （docs/testing.mdパターン3。dynamicWeather.tsが値としてimportするのはURL解析の純関数
// だけで、ランタイムのDOM依存が無いことを確認済み）。
import { describe, expect, it } from "vitest";
import {
  DISASTER_SOURCES,
  DYNAMIC_WEATHER_LAYER_IDS,
  formatDynamicFrameTime,
  frameIndexForTime,
  observationIndexForTime,
  gridCellRing,
  isWithinFutureWindow,
  mergeFrameTimes,
  nearestTimeIndex,
  tileDeliveryFailureLayerIds,
} from "./dynamicWeather";
import type { DynamicWeatherGroupState, DynamicWeatherLayerId } from "./dynamicWeather";

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
    const times = [
      new Date("2026-08-20T00:00:00+09:00"),
      new Date("2026-08-20T03:00:00+09:00"),
      new Date("2026-08-20T06:00:00+09:00"),
    ];

    it("対象時刻に最も近いindexを返す", () => {
      expect(nearestTimeIndex(times, new Date("2026-08-20T04:40:00+09:00"))).toBe(2);
      expect(nearestTimeIndex(times, new Date("2026-08-20T01:00:00+09:00"))).toBe(0);
    });

    it("空配列なら0を返す", () => {
      expect(nearestTimeIndex([], new Date())).toBe(0);
    });
  });

  // 予測を持たないレイヤー（観測だけが届く）。配信の遅れで共有時刻が最新フレームより後ろに
  // なるのは常態で、frameIndexForTimeの規約をそのまま当てると常に何も描かれない（実測:
  // 雷放電の最新フレームが5.0分前で、5分刻みの共有時刻が必ずその後ろに来る、T861）。
  describe("observationIndexForTime（予測を持たないレイヤー）", () => {
    const frames = [{ time: new Date("2026-08-20T12:50:00+09:00") }, { time: new Date("2026-08-20T12:55:00+09:00") }];

    it("配信の遅れのぶん後ろを指していても、最新の観測を返す", () => {
      expect(observationIndexForTime(frames, new Date("2026-08-20T13:00:00+09:00"))).toBe(1);
      expect(observationIndexForTime(frames, new Date("2026-08-20T13:14:00+09:00"))).toBe(1);
    });

    it("許容の幅を超えて先を指していればnull（古い観測をその時刻の値として出さない）", () => {
      expect(observationIndexForTime(frames, new Date("2026-08-20T13:20:00+09:00"))).toBeNull();
      expect(observationIndexForTime(frames, new Date("2026-08-20T20:00:00+09:00"))).toBeNull();
    });

    it("範囲内の時刻はframeIndexForTimeと同じく最も近いフレーム", () => {
      expect(observationIndexForTime(frames, new Date("2026-08-20T12:51:00+09:00"))).toBe(0);
    });

    it("最初のフレームより前はnull（過去は範囲外のまま）", () => {
      expect(observationIndexForTime(frames, new Date("2026-08-20T11:00:00+09:00"))).toBeNull();
    });

    it("フレームが空ならnull", () => {
      expect(observationIndexForTime([], new Date())).toBeNull();
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

  describe("DYNAMIC_WEATHER_LAYER_IDS", () => {
    it('災害の各ソースはチップを持たず、"disaster"1つに集約されている', () => {
      // 母集団はDISASTER_SOURCESから引く。ソースを足したぶんも自動で対象に入る。
      expect(DYNAMIC_WEATHER_LAYER_IDS).toContain("disaster");
      expect(DISASTER_SOURCES.length).toBeGreaterThan(0);
      for (const source of DISASTER_SOURCES) {
        expect(DYNAMIC_WEATHER_LAYER_IDS).not.toContain(source.key);
      }
    });
  });
});

// 配信元のタイルが返らない状態は空タイルで代替されるため、フェッチ側のerrorには現れない
// （jmaTileProtocol.ts）。表示中のフレームと突き合わせて、そのタイルを出しているチップだけを
// エラーにする。
describe("tileDeliveryFailureLayerIds", () => {
  const BT = "20260914123000";
  const PREFIX = `https://example.test/api/jma-tile/bosai/jmatile/data/risk/${BT}/immed0/${BT}/surf/land/`;
  const TEMPLATE = `${PREFIX}{z}/{x}/{y}.png`;

  function groups(state: DynamicWeatherGroupState): Partial<Record<DynamicWeatherLayerId, DynamicWeatherGroupState>> {
    return { disaster: state };
  }

  it("表示中のタイルの配信が落ちていればそのチップを返す", () => {
    const result = tileDeliveryFailureLayerIds(
      groups({ landslide: { visible: true, payload: { kind: "rasterTile", tileUrlTemplate: TEMPLATE } } }),
      new Map([["land", PREFIX]]),
    );
    expect(result).toEqual(["disaster"]);
  });

  it("非表示のソースは対象外", () => {
    const result = tileDeliveryFailureLayerIds(
      groups({ landslide: { visible: false, payload: { kind: "rasterTile", tileUrlTemplate: TEMPLATE } } }),
      new Map([["land", PREFIX]]),
    );
    expect(result).toEqual([]);
  });

  // 失敗の記録はbasetime・validtimeを含むため、フレームが進めば古い失敗は当たらない。
  it("別のフレームを表示していれば当たらない", () => {
    const result = tileDeliveryFailureLayerIds(
      groups({ landslide: { visible: true, payload: { kind: "rasterTile", tileUrlTemplate: TEMPLATE } } }),
      new Map([["land", PREFIX.replace(BT, "20260914124000")]]),
    );
    expect(result).toEqual([]);
  });

  // 格子・GeoJSONを自前のfetchで取る表現は、フェッチ自身のloading/errorが状態を持つ。
  it("タイルを配信元から引かない表現は対象外", () => {
    const result = tileDeliveryFailureLayerIds(
      groups({
        liden: { visible: true, payload: { kind: "gridMark", geojson: { type: "FeatureCollection", features: [] } } },
      }),
      new Map([["land", PREFIX]]),
    );
    expect(result).toEqual([]);
  });
});
