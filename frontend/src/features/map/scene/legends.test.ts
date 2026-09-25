// @vitest-environment node
/** 凡例の見本が、地図に実際に描かれるものだけを示すこと。 */
import { describe, expect, it } from "vitest";

import { pointGroup } from "@/features/map/scene/groups/points";
import { LEGEND_NO_DATA_KEY } from "@/lib/mapDisplay/mapColorLegend";

import { createExpression } from "@maplibre/maplibre-gl-style-spec";

import { ROAD_OTHER_KEY, ROAD_TRACKS, roadLineGroup, roadTrackAxis } from "./groups/roadLines";
import { pointLegendAxes, roadLegendAxes } from "./legends";

const TILES = {
  poi: ["https://example.test/poi/{z}/{x}/{y}"],
  accident: ["https://example.test/accident/{z}/{x}/{y}"],
  poiSourceLayer: "poi",
  accidentSourceLayer: "accident",
  minZoom: 10,
  maxZoom: 14,
};

function paintOf(role: string) {
  const layer = pointGroup.build({ tiles: TILES, visible: {}, hiddenKeys: {} }).layers.find((l) => l.role === role);
  if (layer === undefined) throw new Error(`${role} の層が無い`);
  return layer.paint as Record<string, unknown>;
}

/** 式の中に現れる値をすべて拾う（`case`の枝も既定値も）。 */
function valuesIn(expression: unknown): unknown[] {
  return Array.isArray(expression) ? expression.flatMap(valuesIn) : [expression];
}

describe("点の凡例", () => {
  const axes = pointLegendAxes();

  it.each(axes.map((axis) => [axis.axisId, axis] as const))("%s の見本は地図の点に現れる", (_, axis) => {
    const paint = paintOf(axis.layerId);
    for (const entry of axis.entries) {
      if (entry.diameterPx === undefined) {
        expect(valuesIn(paint["circle-color"])).toContain(entry.color);
      } else {
        expect(valuesIn(paint["circle-radius"])).toContain(entry.diameterPx / 2);
      }
    }
  });

  it("大きさで示す行は、行ごとに違う大きさを持つ", () => {
    for (const axis of axes) {
      const sizes = axis.entries.flatMap((entry) => (entry.diameterPx === undefined ? [] : [entry.diameterPx]));
      expect(new Set(sizes).size).toBe(sizes.length);
    }
  });
});

// 見本は地図と同じ形で見せる（凡例の見本の台の中身は、線の行は線、点の行は点）。
describe("凡例の見本の形", () => {
  it("道の線の凡例の行は、受け皿の行も含めてどれも線の見本にする", () => {
    const entries = roadLegendAxes().flatMap((axis) => axis.entries);
    expect(entries.length).toBeGreaterThan(0);
    expect(entries.every((entry) => entry.lineWidthPx !== undefined)).toBe(true);
  });

  it("点の凡例の行は、線の見本にしない", () => {
    expect(
      pointLegendAxes()
        .flatMap((axis) => axis.entries)
        .some((entry) => entry.lineWidthPx !== undefined),
    ).toBe(false);
  });
});

// 「不明」（タグが無い）と、分類の外の値（その他・該当なし）は別の行。値が無いのは「不明」だけで、
// 値の無い道がタイルに現れうる属性だけが「不明」の行を持つ。
function roadLineWidth(attrId: string, properties: Record<string, unknown>): unknown {
  const layer = roadLineGroup
    .build({
      tiles: { urls: ["https://example.test/{z}/{x}/{y}"], sourceLayer: "road", minZoom: 10, maxZoom: 14 },
      visible: { [attrId]: true },
      hiddenKeys: {},
      inspectedWayId: null,
    })
    .layers.find((candidate) => candidate.role === attrId);
  const compiled = createExpression(layer?.paint?.["line-width"], "paint");
  if (compiled.result !== "success") throw new Error(`${attrId} の太さの式が評価できない`);
  return compiled.value.evaluateWithoutErrorHandling({ zoom: 14 } as never, { type: 2, properties } as never, {});
}

describe("道の線の凡例の見本の太さ", () => {
  it.each(ROAD_TRACKS.map((track) => [track.attr_id, track] as const))(
    "%s: 行の見本は、その行の道を地図が描く太さと同じ",
    (attrId, track) => {
      const axis = roadLegendAxes().find((candidate) => candidate.axisId === attrId);
      if (axis === undefined) throw new Error(`${attrId} の凡例が無い`);
      const property = roadTrackAxis(track).property;
      for (const category of roadTrackAxis(track).categories) {
        const entry = axis.entries.find((candidate) => candidate.key === category.key);
        expect(entry?.lineWidthPx).toBe(roadLineWidth(attrId, { [property]: category.values[0] }));
      }
      const missing = axis.entries.find((entry) => entry.key === LEGEND_NO_DATA_KEY);
      if (missing !== undefined) expect(missing.lineWidthPx).toBe(roadLineWidth(attrId, {}));
    },
  );
});

describe("道の線の凡例の受け皿", () => {
  it.each(ROAD_TRACKS.map((track) => [track.attr_id, track] as const))(
    "%s: 分類の後に分類の外の値の行と（値の無い道が現れうるなら）「不明」が並び、受け皿は「不明」だけで、鍵は重ならない",
    (attrId, track) => {
      const axis = roadLegendAxes().find((candidate) => candidate.axisId === attrId);
      if (axis === undefined) throw new Error(`${attrId} の凡例が無い`);
      const keys = axis.entries.map((entry) => entry.key);
      const tail =
        roadTrackAxis(track).missing_semantics === "unknown" ? [ROAD_OTHER_KEY, LEGEND_NO_DATA_KEY] : [ROAD_OTHER_KEY];
      expect(keys.slice(-tail.length)).toEqual(tail);
      expect(new Set(keys).size).toBe(keys.length);
      expect(axis.entries.filter((entry) => entry.isFallback).map((entry) => entry.key)).toEqual(
        roadTrackAxis(track).missing_semantics === "unknown" ? [LEGEND_NO_DATA_KEY] : [],
      );
    },
  );
});
