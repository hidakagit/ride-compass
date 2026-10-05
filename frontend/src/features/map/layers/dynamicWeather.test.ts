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
const noFrames: typeof frames = [];

describe("frameIndexForTime（共有時刻に対して描くコマ）", () => {
  it.each([
    ["範囲内なら最も近いコマ", frames, at(6), 1],
    ["最初のコマの前は1秒の揺れまで範囲内", frames, new Date(at(0).getTime() - 1000), 0],
    ["最初のコマより前は描かない（過ぎた時刻に最初のコマを出し続けない）", frames, at(-1), null],
    ["最後のコマの後は1秒の揺れまで範囲内", frames, new Date(at(20).getTime() + 1000), 2],
    ["最後のコマより後は描かない", frames, new Date(at(20).getTime() + 1001), null],
    ["コマが無ければ描かない", noFrames, at(0), null],
  ])("%s", (_scene, given, target, expected) => {
    expect(frameIndexForTime(given, target)).toBe(expected);
  });
});

describe("observationIndexForTime（観測だけが届くレイヤーのコマ）", () => {
  const delay = 20 * MINUTE;

  it.each([
    ["最新の観測より後ろでも、届くまでの遅れの幅の間は最新の観測", frames, at(40), 2],
    ["遅れの幅より先では描かない", frames, at(40, 1), null],
    ["観測の範囲内は最も近いコマ", frames, at(12), 1],
    ["観測が無ければ描かない", noFrames, at(0), null],
  ])("%s", (_scene, given, target, expected) => {
    expect(observationIndexForTime(given, target, delay)).toBe(expected);
  });
});

describe("isWithinFutureWindow（単発の予測を出す時間窓）", () => {
  const now = at(0);
  it("今から窓の幅まで（両端を含み、今の側は1秒の揺れを許す）", () => {
    expect(isWithinFutureWindow(new Date(now.getTime() - 1000), now, 60 * MINUTE)).toBe(true);
    expect(isWithinFutureWindow(at(60), now, 60 * MINUTE)).toBe(true);
    expect(isWithinFutureWindow(new Date(now.getTime() - 1001), now, 60 * MINUTE)).toBe(false);
    expect(isWithinFutureWindow(at(60, 1), now, 60 * MINUTE)).toBe(false);
  });
});

describe("gridToFeatureCollection・gridCellRing（格子から地物へ）", () => {
  it("値の取れた点だけを地物にする（欠損した点は飛ばす）", () => {
    const grid = [
      { id: "b", value: null },
      { id: "d", value: 0 },
    ];
    const collection = gridToFeatureCollection(
      grid,
      (point) => point.value,
      (point, value) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [0, 0] },
        properties: { id: point.id, value },
      }),
    );
    expect(collection.features.map((feature) => feature.properties)).toEqual([{ id: "d", value: 0 }]);
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
  // 記録の値は、失敗したタイルのコマのテンプレート（`jmaTileProtocol.ts`が描画ペイロードと同じ文字列で持つ）。
  const TEMPLATE = "https://example.com/risk/20260924000000/none/20260924010000/inund/{z}/{x}/{y}.png";
  const tile = (kind: "rasterTile" | "vectorTile", template = TEMPLATE): DynamicWeatherRenderPayload => ({
    kind,
    tileUrlTemplate: template,
  });
  const failures = new Map([["inund", TEMPLATE]]);
  const group = (payload: DynamicWeatherRenderPayload | undefined, visible = true): DynamicWeatherGroupState => ({
    main: { visible, payload },
  });
  const grid: DynamicWeatherRenderPayload = { kind: "gridFill", geojson: { type: "FeatureCollection", features: [] } };
  const nextFrame = TEMPLATE.replace("20260924010000", "20260924011000");

  it.each([
    [
      "表示中のベクタタイルが、いま失敗しているコマを指す",
      { disaster: group(tile("vectorTile")) },
      failures,
      ["disaster"],
    ],
    [
      "表示中のラスタタイルも同じ",
      { precipitationNowcast: group(tile("rasterTile")) },
      failures,
      ["precipitationNowcast"],
    ],
    ["非表示のソースは対象外", { disaster: group(tile("vectorTile"), false) }, failures, []],
    ["自前で取る表現（格子）は対象外", { precipitationNowcast: group(grid) }, failures, []],
    ["描く中身がまだ無いソースは対象外", { windVector: group(undefined) }, failures, []],
    [
      "フレームが進んで別のコマを指していれば、古い失敗は当たらない",
      { disaster: group(tile("vectorTile", nextFrame)) },
      failures,
      [],
    ],
    ["失敗が無ければ空", { disaster: group(tile("vectorTile")) }, new Map<string, string>(), []],
  ])("%s", (_scene, groups, given, expected) => {
    expect(tileDeliveryFailureLayerIds(groups, given)).toEqual(expected);
  });
});
