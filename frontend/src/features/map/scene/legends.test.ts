// @vitest-environment node
/** 凡例の見本が、地図に実際に描かれるものだけを示すこと。 */
import { describe, expect, it } from "vitest";

import { pointGroup } from "@/features/map/scene/groups/points";
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
    expect(entries.every((entry) => entry.line === true)).toBe(true);
  });

  it("点の凡例の行は、線の見本にしない", () => {
    expect(
      pointLegendAxes()
        .flatMap((axis) => axis.entries)
        .some((entry) => entry.line),
    ).toBe(false);
  });
});
