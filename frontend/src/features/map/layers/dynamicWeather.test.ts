// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  frameIndexForTime,
  gridCellRing,
  gridToFeatureCollection,
  isWithinFutureWindow,
  observationIndexForTime,
  tileDeliveryFailureLayerIds,
  type DynamicWeatherGroupState,
  type DynamicWeatherRenderPayload,
} from "./dynamicWeather";

const at = (minute: number, second = 0) => new Date(Date.UTC(2026, 8, 24, 0, minute, second));
const MINUTE = 60_000;

// 10分おきの3コマ（0分・10分・20分）。
const frames = [0, 10, 20].map((minute) => ({ time: at(minute) }));

describe("frameIndexForTime（共有時刻に対して描くコマ）", () => {
  it("データの範囲内なら最も近いコマ", () => {
    expect(frameIndexForTime(frames, at(0))).toBe(0);
    expect(frameIndexForTime(frames, at(4))).toBe(0);
    expect(frameIndexForTime(frames, at(6))).toBe(1);
    expect(frameIndexForTime(frames, at(20))).toBe(2);
  });

  it("範囲の外なら描かない——過ぎた時刻を指しても、最初のコマを出し続けない", () => {
    expect(frameIndexForTime(frames, at(-1))).toBeNull();
    expect(frameIndexForTime(frames, at(21))).toBeNull();
    expect(frameIndexForTime([], at(0))).toBeNull();
  });

  it("端ちょうどは1秒までの揺れを範囲内に含める", () => {
    expect(frameIndexForTime(frames, new Date(at(0).getTime() - 1000))).toBe(0);
    expect(frameIndexForTime(frames, new Date(at(20).getTime() + 1000))).toBe(2);
    expect(frameIndexForTime(frames, new Date(at(20).getTime() + 1001))).toBeNull();
  });
});

describe("observationIndexForTime（観測だけが届くレイヤーのコマ）", () => {
  const delay = 20 * MINUTE;

  it("最新の観測より後ろでも、届くまでの遅れの幅の間は最新の観測を出し、それより先では描かない", () => {
    expect(observationIndexForTime(frames, at(35), delay)).toBe(2);
    expect(observationIndexForTime(frames, at(40), delay)).toBe(2);
    expect(observationIndexForTime(frames, at(40, 1), delay)).toBeNull();
  });

  it("観測の範囲内は最も近いコマ、最初の観測より前と空は描かない", () => {
    expect(observationIndexForTime(frames, at(12), delay)).toBe(1);
    expect(observationIndexForTime(frames, at(-5), delay)).toBeNull();
    expect(observationIndexForTime([], at(0), delay)).toBeNull();
  });
});

describe("isWithinFutureWindow（単発の予測を出す時間窓）", () => {
  const now = at(0);
  it("今から窓の幅まで（両端を含み、今の側は1秒の揺れを許す）", () => {
    expect(isWithinFutureWindow(now, now, 60 * MINUTE)).toBe(true);
    expect(isWithinFutureWindow(new Date(now.getTime() - 1000), now, 60 * MINUTE)).toBe(true);
    expect(isWithinFutureWindow(at(60), now, 60 * MINUTE)).toBe(true);
    expect(isWithinFutureWindow(new Date(now.getTime() - 1001), now, 60 * MINUTE)).toBe(false);
    expect(isWithinFutureWindow(at(60, 1), now, 60 * MINUTE)).toBe(false);
  });
});

describe("gridToFeatureCollection・gridCellRing（格子から地物へ）", () => {
  it("値の取れた点だけを、並びを保って地物にする（欠損した点は飛ばす）", () => {
    const grid = [
      { id: "a", value: 1 },
      { id: "b", value: null },
      { id: "c", value: undefined },
      { id: "d", value: 0 },
    ];
    const collection = gridToFeatureCollection(
      grid,
      (point) => point.value ?? null,
      (point, value) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [0, 0] },
        properties: { id: point.id, value },
      }),
    );
    expect(collection.type).toBe("FeatureCollection");
    expect(collection.features.map((feature) => feature.properties)).toEqual([
      { id: "a", value: 1 },
      { id: "d", value: 0 },
    ]);
  });

  it("格子点を中心とする1辺spacingの閉じた正方形", () => {
    expect(gridCellRing(35, 139, 0.1)).toEqual([
      [138.95, 34.95],
      [139.05, 34.95],
      [139.05, 35.05],
      [138.95, 35.05],
      [138.95, 34.95],
    ]);
  });
});

describe("tileDeliveryFailureLayerIds（配信が止まっている要素を表示中のチップ）", () => {
  const PREFIX = "https://www.jma.go.jp/bosai/jmatile/data/risk/20260924000000/none/20260924010000/surf/inund/";
  const tile = (kind: "rasterTile" | "vectorTile", prefix = PREFIX): DynamicWeatherRenderPayload => ({
    kind,
    tileUrlTemplate: `${prefix}{z}/{x}/{y}.png`,
  });
  const failures = new Map([["inund", PREFIX]]);
  const group = (payload: DynamicWeatherRenderPayload | undefined, visible = true): DynamicWeatherGroupState => ({
    main: { visible, payload },
  });

  it("表示中のタイルが、いま失敗している要素配下を指すチップ（ラスタ・ベクタとも）", () => {
    expect(tileDeliveryFailureLayerIds({ disaster: group(tile("vectorTile")) }, failures)).toEqual(["disaster"]);
    expect(
      tileDeliveryFailureLayerIds(
        { precipitationNowcast: group(tile("rasterTile")), windVector: group(undefined) },
        failures,
      ),
    ).toEqual(["precipitationNowcast"]);
  });

  it("フレームが進んで別の前半を指していれば、古い失敗は当たらない", () => {
    const nextFrame = PREFIX.replace("20260924010000", "20260924011000");
    expect(tileDeliveryFailureLayerIds({ disaster: group(tile("vectorTile", nextFrame)) }, failures)).toEqual([]);
  });

  it("非表示のソース・自前で取る表現（格子）・要素を読めないURLは対象外", () => {
    const grid: DynamicWeatherRenderPayload = {
      kind: "gridFill",
      geojson: { type: "FeatureCollection", features: [] },
    };
    const foreign: DynamicWeatherRenderPayload = {
      kind: "rasterTile",
      tileUrlTemplate: "https://example.com/{z}/{x}/{y}.png",
    };
    expect(
      tileDeliveryFailureLayerIds(
        { disaster: group(tile("vectorTile"), false), precipitationNowcast: group(grid), windVector: group(foreign) },
        failures,
      ),
    ).toEqual([]);
  });

  it("失敗が無ければ空", () => {
    expect(tileDeliveryFailureLayerIds({ disaster: group(tile("vectorTile")) }, new Map())).toEqual([]);
  });
});
