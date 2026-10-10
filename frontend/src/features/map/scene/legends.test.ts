// @vitest-environment node
/** 凡例の見本が、地図に実際に描かれるものだけを示すこと。 */
import { describe, expect, it } from "vitest";

import { POINT_ICONS, POINT_LAYERS, pointAxisKey, pointGroup } from "@/features/map/scene/groups/points";
import { LEGEND_NO_DATA_KEY } from "@/lib/mapDisplay/mapColorLegend";
import { evaluateExpression as evaluate, matchesFilter } from "@/testing/mapExpressions";

import { ROAD_OTHER_KEY, ROAD_TRACKS, roadLineGroup, roadTrackAxis, roadTrackHasMissing } from "./groups/roadLines";
import { disasterSourceLegendAxis, pointLegendAxes, roadLegendAxes } from "./legends";

const TILES = {
  urls: {
    poi: ["https://example.test/poi/{z}/{x}/{y}"],
    accident: ["https://example.test/accident/{z}/{x}/{y}"],
    stop_place: ["https://example.test/stop_place/{z}/{x}/{y}"],
  },
  minZoom: 10,
  maxZoom: 14,
};

function layerOf(role: string) {
  const layer = pointGroup.build({ tiles: TILES, visible: {}, hiddenKeys: {} }).layers.find((l) => l.role === role);
  if (layer === undefined) throw new Error(`${role} の層が無い`);
  return layer;
}

function paintOf(role: string) {
  return layerOf(role).paint as Record<string, unknown>;
}

/** 式の中に現れる値をすべて拾う（`case`の枝も既定値も）。 */
function valuesIn(expression: unknown): unknown[] {
  return Array.isArray(expression) ? expression.flatMap(valuesIn) : [expression];
}

// 道と点の分類の説明は源泉の型が空を通さず、受け皿の行の説明は源泉の1か所の定数。災害の要素の説明は源泉で省けるので、ここで見る。
describe("災害の凡例の行の説明", () => {
  const rows = disasterSourceLegendAxis().entries.map((entry) => [entry.label, entry] as const);

  it.each(rows)("「%s」は（i）から開く説明を持つ", (_, entry) => {
    expect(entry.description?.trim()).toBeTruthy();
  });
});

describe("点の凡例", () => {
  const axes = pointLegendAxes();

  it.each(axes.map((axis) => [axis.axisId, axis] as const))("%s の見本は地図の点に現れる", (_, axis) => {
    const paint = paintOf(axis.layerId);
    for (const entry of axis.entries) {
      if (entry.glyph !== undefined) {
        expect(POINT_ICONS).toContainEqual(expect.objectContaining({ color: entry.color, glyph: entry.glyph }));
      } else if (entry.diameterPx === undefined) {
        expect(valuesIn(paint["circle-color"])).toContain(entry.color);
      } else {
        expect(valuesIn(paint["circle-radius"])).toContain(entry.diameterPx / 2);
      }
    }
  });

  // 地図は行の値ごとに登録した絵を引く。見本と違う色・絵記号の絵を引くと、凡例と地図の点が食い違う。
  const glyphAxes = axes.filter((axis) => axis.entries.some((entry) => entry.glyph !== undefined));

  it("絵記号で描く点のレイヤーがある", () => {
    expect(glyphAxes.length).toBeGreaterThan(0);
  });

  it.each(glyphAxes.map((axis) => [axis.axisId, axis] as const))(
    "%s: 行の値の点は、見本と同じ色・同じ絵記号の絵で描かれ、行ごとに違う絵になる",
    (_, axis) => {
      const layer = layerOf(axis.layerId);
      const [pointLayer] = POINT_LAYERS.filter((candidate) => candidate.attr_id === axis.layerId);
      const [colorAxis] = pointLayer.display_axes;
      const iconImage = (layer.layout as Record<string, unknown>)["icon-image"];
      const drawn = colorAxis.categories.map((category) => {
        const entry = axis.entries.find((candidate) => candidate.key === category.key);
        const images = category.values.map((value) =>
          POINT_ICONS.find((icon) => icon.id === evaluate(iconImage, { [colorAxis.property]: value })),
        );
        for (const image of images) {
          expect({ color: image?.color, glyph: image?.glyph }).toEqual({ color: entry?.color, glyph: entry?.glyph });
        }
        return images[0]?.id;
      });
      expect(new Set(drawn).size).toBe(drawn.length);
    },
  );

  it("大きさで示す行は、行ごとに違う大きさを持つ", () => {
    for (const axis of axes) {
      const sizes = axis.entries.flatMap((entry) => (entry.diameterPx === undefined ? [] : [entry.diameterPx]));
      expect(new Set(sizes).size).toBe(sizes.length);
    }
  });
});

// 見本は地図と同じ形で見せる（線の行は線、点の行は点）。
describe("凡例の見本の形", () => {
  it("道の線の凡例の行は、受け皿の行も含めてどれも線の見本にする", () => {
    const entries = roadLegendAxes().flatMap((axis) => axis.entries);
    expect(entries.length).toBeGreaterThan(0);
    expect(entries.every((entry) => entry.line === true)).toBe(true);
  });
});

// 「データなし」（タグが無い）と、分類の外の値（その他・該当なし）は別の行。値の無い道がタイルに現れうる属性だけが
// 「データなし」の行を持つ。
describe("道の線の凡例の受け皿", () => {
  it.each(ROAD_TRACKS.map((track) => [track.attr_id, track] as const))(
    "%s: 分類の後に分類の外の値の行と（値の無い道が現れうるなら）「データなし」が並び、鍵は重ならない",
    (attrId, track) => {
      const axis = roadLegendAxes().find((candidate) => candidate.axisId === attrId);
      if (axis === undefined) throw new Error(`${attrId} の凡例が無い`);
      const keys = axis.entries.map((entry) => entry.key);
      const tail =
        roadTrackAxis(track).missing_semantics === "unknown" ? [ROAD_OTHER_KEY, LEGEND_NO_DATA_KEY] : [ROAD_OTHER_KEY];
      expect(keys.slice(-tail.length)).toEqual(tail);
      expect(new Set(keys).size).toBe(keys.length);
    },
  );
});

/** 絞り込みがその点の地物を通すか。絞り込みが無ければ全部通る。 */
function passes(filter: unknown, properties: Record<string, unknown>): boolean {
  return filter === undefined || matchesFilter(filter, properties, 1);
}

type LegendAxis = ReturnType<typeof roadLegendAxes>[number];

/** 凡例の鍵ごとの、その行に入る地物。行に入る値を1つずつ持つ地物を作る——行が複数の値を束ねていれば
 * どの値も確かめる。鍵に地物を作れなければ、その鍵は分類にも受け皿にも当たらない。 */
function roadSamples(axis: LegendAxis): Map<string, Record<string, unknown>[]> {
  const track = ROAD_TRACKS.find((candidate) => candidate.attr_id === axis.layerId);
  if (track === undefined) throw new Error(`${axis.layerId} の線が無い`);
  const { property, categories } = roadTrackAxis(track);
  const known = categories[0].values[0];
  const samples = new Map<string, Record<string, unknown>[]>(
    categories.map((category) => [category.key, category.values.map((value) => ({ [property]: value }))]),
  );
  samples.set(ROAD_OTHER_KEY, [{ [property]: typeof known === "boolean" ? !known : "__outside_every_category__" }]);
  if (roadTrackHasMissing(track)) samples.set(LEGEND_NO_DATA_KEY, [{}]);
  return samples;
}

function pointSamples(axis: LegendAxis): Map<string, Record<string, unknown>[]> {
  const layer = POINT_LAYERS.find((candidate) => candidate.attr_id === axis.layerId);
  const own = layer?.display_axes.find((candidate) => pointAxisKey(layer, candidate) === axis.axisId);
  if (layer === undefined || own === undefined) throw new Error(`${axis.axisId} の点の軸が無い`);
  // 他の軸は先頭の行の値にしておく（隠すのはこの軸の行だけなので、他の軸では落ちない）。
  const rest = Object.fromEntries(layer.display_axes.map((other) => [other.property, other.categories[0].values[0]]));
  return new Map(
    own.categories.map((category) => [
      category.key,
      category.values.map((value) => ({ ...rest, [own.property]: value })),
    ]),
  );
}

function roadFilter(axis: LegendAxis, hidden: readonly string[]): unknown {
  return roadLineGroup
    .build({
      tiles: { urls: ["https://example.test/{z}/{x}/{y}"], sourceLayer: "road", minZoom: 10, maxZoom: 14 },
      visible: { [axis.layerId]: true },
      hiddenKeys: { [axis.axisId]: hidden },
      inspectedWayId: null,
    })
    .layers.find((layer) => layer.role === axis.layerId)?.filter;
}

function pointFilter(axis: LegendAxis, hidden: readonly string[]): unknown {
  return pointGroup
    .build({ tiles: TILES, visible: { [axis.layerId]: true }, hiddenKeys: { [axis.axisId]: hidden } })
    .layers.find((layer) => layer.role === axis.layerId)?.filter;
}

// 凡例に出す行はどれも、チェックを外すとその行の地物だけが地図から消える。
describe("凡例の行ごとの絞り込み", () => {
  const cases = [
    ...roadLegendAxes().map((axis) => ({ axis, samples: roadSamples(axis), filterOf: roadFilter })),
    ...pointLegendAxes().map((axis) => ({ axis, samples: pointSamples(axis), filterOf: pointFilter })),
  ].flatMap(({ axis, samples, filterOf }) =>
    axis.entries.map((entry) => [axis.axisId, entry.key, { samples, filter: filterOf(axis, [entry.key]) }] as const),
  );

  it.each(cases)("%s の「%s」を隠すと、その行の地物だけが消える", (_, key, { samples, filter }) => {
    const own = samples.get(key);
    if (own === undefined) throw new Error(`「${key}」の行に入る地物を作れない（分類にも受け皿にも当たらない）`);
    for (const properties of own) expect(passes(filter, properties), JSON.stringify(properties)).toBe(false);
    const others = [...samples].flatMap(([otherKey, properties]) => (otherKey === key ? [] : properties));
    expect(others.length).toBeGreaterThan(0);
    for (const properties of others) expect(passes(filter, properties), JSON.stringify(properties)).toBe(true);
  });
});
