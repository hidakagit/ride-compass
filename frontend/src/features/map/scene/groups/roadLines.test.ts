// @vitest-environment node
/** 道の線の「不明」（タグが無い）と、分類の外の値（その他・該当なし）の描き分けと隠し方。
 * 式はMapLibreと同じ評価器で評価し、1本の道がどう描かれるか・残るかを見る。 */
import { createExpression } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";

import { LEGEND_NO_DATA_KEY } from "@/lib/mapDisplay/mapColorLegend";
import { mapDisplay } from "@/types/generated/mapDisplay";

import { ROAD_OTHER_KEY, ROAD_TRACKS, ROAD_TRACKS_MAX_SPAN_PX, roadLineGroup, roadTrackAxis } from "./roadLines";

const GLOBALS = { zoom: 14 } as never;
const SOLID = [1, 0];

function evaluate(expression: unknown, properties: Record<string, unknown>) {
  const compiled = createExpression(expression, "paint");
  if (compiled.result !== "success") {
    throw new Error(compiled.value.map((error) => `${error.key}: ${error.message}`).join("; "));
  }
  return compiled.value.evaluateWithoutErrorHandling(GLOBALS, { type: 2, properties } as never, {});
}

type Track = (typeof ROAD_TRACKS)[number];

function layerOf(track: Track, hiddenKeys: readonly string[] = []) {
  const layers = roadLineGroup.build({
    tiles: { urls: ["https://example.test/{z}/{x}/{y}"], sourceLayer: "road", minZoom: 10, maxZoom: 14 },
    visible: { [track.attr_id]: true },
    hiddenKeys: { [track.attr_id]: hiddenKeys },
    inspectedWayId: null,
  }).layers;
  const layer = layers.find((candidate) => candidate.role === track.attr_id);
  if (layer === undefined) throw new Error(`${track.attr_id} の線が無い`);
  return layer;
}

/** 分類に入る値の道と、分類の外の値の道。外の値は分類の値と同じ型で作る（真偽の属性ではfalseが「該当しない」）。 */
function roadsOf(track: Track) {
  const property = roadTrackAxis(track).property;
  const known = roadTrackAxis(track).categories[0].values[0];
  const outside = typeof known === "boolean" ? !known : "__outside_every_category__";
  return { known: { [property]: known }, other: { [property]: outside } };
}

const TRACKS = ROAD_TRACKS.map((track) => [track.attr_id, track] as const);
/** 源泉の宣言で、値の無い道がタイルに現れうる属性か（その値を載せる材料の欠け方）。 */
const declaresMissing = (track: Track) => roadTrackAxis(track).missing_semantics === "unknown";
const WITH_MISSING = TRACKS.filter(([, track]) => declaresMissing(track));
const WITHOUT_MISSING = TRACKS.filter(([, track]) => !declaresMissing(track));

describe.each(TRACKS)("道の線（%s）", (_id, track) => {
  it("分類に入る道だけを濃く、分類の外の値の道は薄く、どちらも実線で描く", () => {
    const paint = layerOf(track).paint ?? {};
    const roads = roadsOf(track);
    expect(evaluate(paint["line-opacity"], roads.known)).toBe(mapDisplay.road.knownOpacity);
    expect(evaluate(paint["line-opacity"], roads.other)).toBe(mapDisplay.road.unknownOpacity);
    if (paint["line-dasharray"] === undefined) return;
    expect(evaluate(paint["line-dasharray"], roads.known)).toEqual(SOLID);
    expect(evaluate(paint["line-dasharray"], roads.other)).toEqual(SOLID);
  });

  it("凡例で分類の外の値を隠すと、その道だけが消える", () => {
    const roads = roadsOf(track);
    const filter = layerOf(track, [ROAD_OTHER_KEY]).filter;
    expect(evaluate(filter, roads.known)).toBe(true);
    expect(evaluate(filter, roads.other)).toBe(false);
  });
});

// 値の無い道がタイルに現れうる属性（源泉の`missing_semantics`が`unknown`）。
describe.each(WITH_MISSING)("値の無い道が現れる線（%s）", (_id, track) => {
  it("タグが無い道だけを薄い破線にする", () => {
    const paint = layerOf(track).paint ?? {};
    expect(evaluate(paint["line-dasharray"], {})).toEqual([...mapDisplay.noDataDash]);
    expect(evaluate(paint["line-opacity"], {})).toBe(mapDisplay.road.unknownOpacity);
  });

  it("「不明」を隠すとタグが無い道だけが、分類の外の値を隠すとその道だけが消える", () => {
    const roads = { ...roadsOf(track), missing: {} };
    const kept = (hidden: readonly string[]) =>
      (Object.keys(roads) as (keyof typeof roads)[]).filter((kind) =>
        evaluate(layerOf(track, hidden).filter, roads[kind]),
      );
    expect(kept([LEGEND_NO_DATA_KEY])).toEqual(["known", "other"]);
    expect(kept([ROAD_OTHER_KEY])).toEqual(["known", "missing"]);
  });
});

// タグの不在も確定した値として載る属性（トンネル等）には、値の無い道が無い。
describe.each(WITHOUT_MISSING)("値の無い道が現れない線（%s）", (_id, track) => {
  it("破線を持たない", () => {
    expect(layerOf(track).paint?.["line-dasharray"]).toBeUndefined();
  });
});

function roadOf(track: Track, value: unknown): Record<string, unknown> {
  return value === undefined ? {} : { [roadTrackAxis(track).property]: value };
}

/** 1本の道の、分類の各行・分類の外・値が無い場合。 */
function casesOf(track: Track) {
  const rows = roadTrackAxis(track).categories.map((category) => roadOf(track, category.values[0]));
  return { rows, other: roadsOf(track).other, missing: {} };
}

// 太さは、順序のある分類の行だけが色と同じ順序を重ねて示す。
describe.each(TRACKS)("道の線の太さ（%s）", (_id, track) => {
  it("行の道は並びの先頭ほど太いか、どれも同じ太さで、分類の外・不明の道は他の線と同じ太さ", () => {
    const width = layerOf(track).paint?.["line-width"];
    const cases = casesOf(track);
    const rows = cases.rows.map((road) => evaluate(width, road) as number);
    const ordered = rows.every((w, index) => index === 0 || w < rows[index - 1]);
    expect(ordered || rows.every((w) => w === mapDisplay.road.lineWidthPx)).toBe(true);
    expect(Math.min(...rows)).toBe(mapDisplay.road.lineWidthPx);
    expect(evaluate(width, cases.other)).toBe(mapDisplay.road.lineWidthPx);
    expect(evaluate(width, cases.missing)).toBe(mapDisplay.road.lineWidthPx);
  });
});

describe("道の線をすべて出したときの並び", () => {
  const layers = roadLineGroup
    .build({
      tiles: { urls: ["https://example.test/{z}/{x}/{y}"], sourceLayer: "road", minZoom: 10, maxZoom: 14 },
      visible: Object.fromEntries(ROAD_TRACKS.map((track) => [track.attr_id, true])),
      hiddenKeys: {},
      inspectedWayId: null,
    })
    .layers.filter((layer) => ROAD_TRACKS.some((track) => track.attr_id === layer.role));

  /** 各線の値を1つずつ取り替えた道。どの線がどの太さになる道でも並びが崩れないことを見る。 */
  const roads = ROAD_TRACKS.flatMap((varied) => {
    const cases = casesOf(varied);
    return [...cases.rows, cases.other, cases.missing].map((own) => ({
      ...Object.assign({}, ...ROAD_TRACKS.map((track) => casesOf(track).rows[0])),
      ...(Object.keys(own).length === 0 ? { [roadTrackAxis(varied).property]: undefined } : own),
    }));
  });

  it.each(roads.map((road) => [JSON.stringify(road), road] as const))(
    "%s: 隣どうしは重ね幅だけ重なって隙間なく並び、どの線も隠れきらず、帯の中央が道の位置に来る",
    (_label, road) => {
      const properties = Object.fromEntries(Object.entries(road).filter(([, value]) => value !== undefined));
      const lines = layers
        .map((layer) => ({
          width: evaluate(layer.paint?.["line-width"], properties) as number,
          offset: evaluate(layer.paint?.["line-offset"], properties) as number,
        }))
        .sort((a, b) => a.offset - b.offset);
      const overlap = mapDisplay.road.trackOverlapPx;
      for (let i = 1; i < lines.length; i++) {
        const gap = lines[i].offset - lines[i].width / 2 - (lines[i - 1].offset + lines[i - 1].width / 2);
        expect(gap).toBeCloseTo(-overlap);
      }
      for (const line of lines) expect(line.width - 2 * overlap).toBeGreaterThan(0);
      const left = lines[0].offset - lines[0].width / 2;
      const right = lines[lines.length - 1].offset + lines[lines.length - 1].width / 2;
      expect(left + right).toBeCloseTo(0);
      expect(right - left).toBeLessThanOrEqual(ROAD_TRACKS_MAX_SPAN_PX);
    },
  );

  it("1本だけ出すと、太さによらず道の位置に描く", () => {
    for (const track of ROAD_TRACKS) {
      const offset = layerOf(track).paint?.["line-offset"];
      for (const road of casesOf(track).rows) expect(evaluate(offset, road)).toBe(0);
    }
  });
});
