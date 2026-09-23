// @vitest-environment node
// `lens.ts`——レンズの1つの値から、地図の塗り分け・取りに行く軸・凡例・選択肢を導く。
//
// ここで見ないもの:
// - 凡例の段そのもの（境界・色・ラベルの規則）→ `mapColorLegend.test.ts`・`axisLayers.test.ts`
// - 取得状態の判定順序 → `mapLayers.test.ts`（`deriveFetchLayerStatus`）
import { describe, expect, it } from "vitest";

import { EMPTY_CATALOG } from "@/lib/axisCatalog";

import { catalogOf, catalogEntry, dedicatedEntry, rampEntry } from "./__fixtures__/catalog";
import {
  lensAxisVisibility,
  lensBackgroundShown,
  lensDataStatus,
  lensDedicatedWayValueVisibility,
  lensFetchAxes,
  lensLegend,
  lensOptions,
  restoreLens,
} from "./lens";

// ramp表示を持つ軸・専用配信を持つ軸・どちらも持たない軸。
const CATALOG = catalogOf([rampEntry("r", [1, 2]), dedicatedEntry("d", [0]), catalogEntry({ axis_id: "p" })]);

function legendOf(lens: string, hasDetail: boolean) {
  return lensLegend({
    lens,
    hasDetail,
    routeStyleModes: CATALOG.routeStyleModes,
    rampAxes: CATALOG.rampAxes,
    dedicatedAxes: CATALOG.dedicatedAxes,
  });
}

describe("lensBackgroundShown（全道路を塗り続けるか）", () => {
  it("ルート確定前は常に塗り、確定後は「ルート後も薄く塗る」の間だけ塗る", () => {
    expect(lensBackgroundShown(false, false)).toBe(true);
    expect(lensBackgroundShown(true, true)).toBe(true);
    expect(lensBackgroundShown(true, false)).toBe(false);
  });
});

describe("全道路の塗り分け（ramp軸・専用配信軸）", () => {
  it("レンズが指す軸のレイヤーだけを出し、他の軸のレイヤーは出さない", () => {
    expect(lensAxisVisibility(CATALOG.rampAxes, "r", true)).toEqual({ "axis:r": true });
    expect(lensDedicatedWayValueVisibility(CATALOG.dedicatedAxes, "r", true)).toEqual({ dAxis: false });
    expect(lensAxisVisibility(CATALOG.rampAxes, "d", true)).toEqual({ "axis:r": false });
    expect(lensDedicatedWayValueVisibility(CATALOG.dedicatedAxes, "d", true)).toEqual({ dAxis: true });
  });

  it("全道路を塗らない間は、レンズが指す軸のレイヤーも出さない", () => {
    expect(lensAxisVisibility(CATALOG.rampAxes, "r", false)).toEqual({ "axis:r": false });
    expect(lensDedicatedWayValueVisibility(CATALOG.dedicatedAxes, "d", false)).toEqual({ dAxis: false });
  });
});

describe("lensFetchAxes（値を取りに行く専用配信軸）", () => {
  it("塗っている専用配信軸だけを取りに行く", () => {
    expect(lensFetchAxes(CATALOG.dedicatedAxes, "d", true).map((axis) => axis.axisId)).toEqual(["d"]);
    expect(lensFetchAxes(CATALOG.dedicatedAxes, "r", true)).toEqual([]);
    expect(lensFetchAxes(CATALOG.dedicatedAxes, "d", false)).toEqual([]);
  });
});

describe("lensLegend（レンズの凡例）", () => {
  it("ルート確定前は、その軸で全道路を塗る手段の段を出す", () => {
    expect(legendOf("r", false).map((entry) => entry.label)).toEqual(["1未満", "1〜2", "2以上"]);
    expect(legendOf("d", false).map((entry) => entry.label)).toEqual(["0未満", "0以上", "データなし"]);
  });

  it("ルート確定の前後で段の鍵が同じなので、隠した段がルート生成をまたいで残る", () => {
    const before = legendOf("d", false).map((entry) => entry.key);
    const after = legendOf("d", true);
    expect(after.map((entry) => entry.key)).toEqual(before);
    // 確定後はルート線の絞り込みに使う述語を持つ。
    expect(after.length).toBeGreaterThan(0);
    for (const entry of after) expect(entry.filter).toBeDefined();
  });

  it("地図がそのレンズで何も塗らない間は、凡例を出さない", () => {
    expect(legendOf("difficulty", false)).toEqual([]);
    expect(legendOf("p", false)).toEqual([]);
    expect(legendOf("none", true)).toEqual([]);
  });
});

describe("lensOptions（レンズの選択肢）", () => {
  const options = lensOptions({
    axes: CATALOG.axes,
    rampAxes: CATALOG.rampAxes,
    dedicatedAxes: CATALOG.dedicatedAxes,
    axisWeights: { r: 0.5, d: 0 },
    defaultWeights: { p: 0.3 },
    axisColors: { r: "#123456" },
  });
  const byId = Object.fromEntries(options.map((option) => [option.id, option]));

  it("公開軸をカタログの並びのまま並べ、重み0の軸は未使用として残す", () => {
    expect(options.map((option) => option.id)).toEqual(["r", "d", "p"]);
    expect(byId.r.unused).toBe(false);
    expect(byId.d.unused).toBe(true);
  });

  it("評価の設定に重みが無い軸は、軸の既定重みで未使用かを決める", () => {
    expect(byId.p.unused).toBe(false);
  });

  it("ルート確定前に塗る手段を持たない軸だけが「ルート後のみ」になる", () => {
    expect(byId.r.routeOnly).toBe(false);
    expect(byId.d.routeOnly).toBe(false);
    expect(byId.p.routeOnly).toBe(true);
  });

  it("軸の色はルート結果と同じ配色を使う", () => {
    expect(byId.r.color).toBe("#123456");
  });
});

describe("lensDataStatus（レンズのピルの状態ドット）", () => {
  const result = { values: new Map<string, number>(), loading: false, error: false, hasFetched: true };

  it("取りに行っていない軸は状態を持たない", () => {
    expect(lensDataStatus(undefined)).toBeUndefined();
  });

  it("取得に失敗したら失敗、取り終えて値が1つも無ければ空、値があれば何も出さない", () => {
    expect(lensDataStatus({ ...result, error: true })).toBe("error");
    expect(lensDataStatus(result)).toBe("empty");
    expect(lensDataStatus({ ...result, values: new Map([["1", 3]]) })).toBeUndefined();
  });
});

describe("restoreLens（保存したレンズの復元）", () => {
  it("いま選べるモードにあるときだけ読む", () => {
    expect(restoreLens("d", CATALOG.routeStyleModes)).toBe("d");
    expect(restoreLens("unpublished", CATALOG.routeStyleModes)).toBeNull();
  });

  it("軸カタログが届く前は、軸を指す保存値を読まない", () => {
    expect(restoreLens("d", EMPTY_CATALOG.routeStyleModes)).toBeNull();
    expect(restoreLens("difficulty", EMPTY_CATALOG.routeStyleModes)).toBe("difficulty");
  });
});
