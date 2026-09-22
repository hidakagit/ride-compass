// @vitest-environment node
/** 地図が描く分類の宣言が、源泉と食い違っていないか。
 *
 * 見るのは**導出した母集団の全件に対する不変条件**だけで、個々の値は書き写さない。
 * backendが値を1つ足したとき、ここが落ちる。
 */
import { describe, expect, it } from "vitest";

import poiKinds from "@/types/generated/poi-kinds.json";
import primaryAttributes from "@/types/generated/primary-attributes.json";
import surfaceTags from "@/types/generated/surface-tags.json";

import { POINT_LAYERS } from "./points";
import { ROAD_TRACKS } from "./roadLines";

const GEOMETRY_OF = new Map(
  (primaryAttributes as { attr_id: string; geometry: string }[]).map((attr) => [attr.attr_id, attr.geometry]),
);

const valuesOf = (categories: readonly { readonly values: readonly (string | boolean)[] }[]): Set<string | boolean> =>
  new Set(categories.flatMap((category) => [...category.values]));

describe("道路の線の分類", () => {
  it("線で描くのは、源泉が線と言っている属性だけ", () => {
    for (const track of ROAD_TRACKS) {
      expect(GEOMETRY_OF.get(track.attrId), track.attrId).toBe("line");
    }
  });

  // 片側だけタグを増減すると、地図の色と評価が食い違う（表示上はアスファルトなのに
  // 評価では未分類、という状態になる）。
  it("路面の分類は、正準分類済みのタグを1つ残らず拾う", () => {
    const declared = valuesOf(ROAD_TRACKS.find((track) => track.attrId === "surface")?.categories ?? []);
    const canonical = [...surfaceTags.good, ...surfaceTags.bad];

    expect([...canonical].filter((tag) => !declared.has(tag))).toEqual([]);
  });

  it("分類の鍵と色は、1つの線の中で重複しない", () => {
    for (const track of ROAD_TRACKS) {
      const keys = track.categories.map((category) => category.key);
      const colors = track.categories.map((category) => category.color);
      expect(new Set(keys).size, track.attrId).toBe(keys.length);
      expect(new Set(colors).size, track.attrId).toBe(colors.length);
    }
  });
});

describe("点の分類", () => {
  it("点で描くのは、源泉が点と言っている属性だけ", () => {
    for (const layer of POINT_LAYERS) {
      expect(GEOMETRY_OF.get(layer.role), layer.role).toBe("point");
    }
  });

  // 分類を持たない種別はbaseFilterに弾かれて地図から完全に消える（凡例にも出ないため
  // 「データが無い」としか見えない）。
  it("POIの分類は、配信される種別を1つ残らず拾う", () => {
    const declaredFor = (role: string) =>
      valuesOf(POINT_LAYERS.find((layer) => layer.role === role)?.axes.flatMap((axis) => axis.categories) ?? []);

    expect(poiKinds.stop.filter((kind) => !declaredFor("stop_poi").has(kind))).toEqual([]);
    expect(poiKinds.supply.filter((kind) => !declaredFor("supply_poi").has(kind))).toEqual([]);
  });

  it("軸の鍵は、点をまたいでも重複しない", () => {
    const keys = POINT_LAYERS.flatMap((layer) => layer.axes.map((axis) => `${layer.role}:${axis.key}`));
    expect(new Set(keys).size).toBe(keys.length);
  });
});
