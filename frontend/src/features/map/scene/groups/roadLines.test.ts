// @vitest-environment node
/** 道の線の「不明」（タグが無い）と、分類の外の値（その他・該当なし）の描き分け。
 * 式はMapLibreと同じ評価器で評価し、1本の道がどう描かれるかを見る。凡例で隠したときに残るかは
 * `legends.test.ts`の「凡例の行ごとの絞り込み」が凡例の全部の行で見る。 */
import { describe, expect, it } from "vitest";

import { evaluateExpression as evaluate } from "@/testing/mapExpressions";
import { mapDisplay } from "@/types/generated/mapDisplay";

import { ROAD_TRACKS, roadLineGroup, roadTrackAxis } from "./roadLines";

const SOLID = [1, 0];

type Track = (typeof ROAD_TRACKS)[number];

function layerOf(track: Track) {
  const layers = roadLineGroup.build({
    tiles: { urls: ["https://example.test/{z}/{x}/{y}"], sourceLayer: "road", minZoom: 10, maxZoom: 14 },
    visible: { [track.attr_id]: true },
    hiddenKeys: {},
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
  it("分類に入る道だけを濃く、分類の外の値の道は薄く描く", () => {
    const paint = layerOf(track).paint ?? {};
    const roads = roadsOf(track);
    expect(evaluate(paint["line-opacity"], roads.known)).toBe(mapDisplay.road.knownOpacity);
    expect(evaluate(paint["line-opacity"], roads.other)).toBe(mapDisplay.road.unknownOpacity);
  });
});

// 値の無い道がタイルに現れうる属性（源泉の`missing_semantics`が`unknown`）。
describe.each(WITH_MISSING)("値の無い道が現れる線（%s）", (_id, track) => {
  it("タグが無い道だけを破線にし、分類の外の値の道は実線で描く", () => {
    const paint = layerOf(track).paint ?? {};
    expect(evaluate(paint["line-dasharray"], {})).toEqual([...mapDisplay.noDataDash]);
    expect(evaluate(paint["line-dasharray"], roadsOf(track).other)).toEqual(SOLID);
  });
});

// タグの不在も確定した値として載る属性（トンネル等）には、値の無い道が無い。
describe.each(WITHOUT_MISSING)("値の無い道が現れない線（%s）", (_id, track) => {
  it("破線を持たない", () => {
    expect(layerOf(track).paint?.["line-dasharray"]).toBeUndefined();
  });
});
