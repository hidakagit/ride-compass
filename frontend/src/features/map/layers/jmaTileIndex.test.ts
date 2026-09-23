// @vitest-environment node
import { describe, expect, it } from "vitest";

import type { JmaTileIndexResponse } from "./jmaTileIndex";
import { buildJmaTileIndexLookup, isKnownEmptyTile, parseJmaTileElement } from "./jmaTileIndex";

const BASETIME = "20260924000000";
const VALIDTIME = "20260924010000";
const HOST = "https://www.jma.go.jp/bosai/jmatile/data/risk";
// 5/28/12 は東経135〜146度・北緯32〜41度あたり（関東を含む）。
const tileUrl = ({
  element = "inund",
  frame = `${BASETIME}/none/${VALIDTIME}`,
  z = 5,
  x = 28,
  y = 12,
  ext = "png",
} = {}) => `${HOST}/${frame}/surf/${element}/${z}/${x}/${y}.${ext}`;

const JAPAN = { min_longitude: 122, min_latitude: 24, max_longitude: 146, max_latitude: 46 };

function response(elements: JmaTileIndexResponse["elements"]): JmaTileIndexResponse {
  return { available: true, coverage: JAPAN, elements };
}

const inundAt = (zooms: Record<string, number[][]>) =>
  response({ inund: { basetime: BASETIME, validtime: VALIDTIME, member: "none", zooms } });

describe("buildJmaTileIndexLookup（在否インデックスの前処理）", () => {
  it("インデックスが無い・網羅範囲か要素が欠けた応答は、使えるインデックス無し", () => {
    expect(buildJmaTileIndexLookup(null)).toBeNull();
    expect(buildJmaTileIndexLookup({ available: false })).toBeNull();
    expect(buildJmaTileIndexLookup({ available: true, elements: {} })).toBeNull();
    expect(buildJmaTileIndexLookup({ available: true, coverage: JAPAN })).toBeNull();
  });

  it("フレームを照合できない要素（basetime・validtimeの欠け）は載せず、1つも残らなければ無し", () => {
    const lookup = buildJmaTileIndexLookup(
      response({
        inund: { basetime: BASETIME, validtime: VALIDTIME, member: "none", zooms: {} },
        flood: { basetime: null, validtime: VALIDTIME, member: "none", zooms: {} },
        land: { basetime: BASETIME, validtime: null, member: "none", zooms: {} },
      }),
    );
    expect([...(lookup?.elements.keys() ?? [])]).toEqual(["inund"]);
    expect(
      buildJmaTileIndexLookup(response({ flood: { basetime: null, validtime: null, member: "none", zooms: {} } })),
    ).toBeNull();
  });
});

describe("isKnownEmptyTile（取得を省いてよいか）", () => {
  const lookup = buildJmaTileIndexLookup(inundAt({ "5": [[28, 13]] }));

  it("インデックスの網羅範囲内で、載っていないタイルだけを空と判定する", () => {
    expect(isKnownEmptyTile(lookup, tileUrl())).toBe(true);
    expect(isKnownEmptyTile(lookup, tileUrl({ y: 13 }))).toBe(false);
    expect(isKnownEmptyTile(lookup, tileUrl({ z: 6, x: 56, y: 26 }))).toBe(true);
  });

  it("ベクタタイル（.pbf）のURLも同じに読む", () => {
    expect(isKnownEmptyTile(lookup, tileUrl({ ext: "pbf" }))).toBe(true);
  });

  it("判断できないときは取りに行く: インデックス無し・読めないURL・載っていない要素", () => {
    expect(isKnownEmptyTile(null, tileUrl())).toBe(false);
    expect(isKnownEmptyTile(lookup, "https://example.com/tile/5/28/12.png")).toBe(false);
    expect(isKnownEmptyTile(lookup, tileUrl({ element: "flood" }))).toBe(false);
  });

  it("フレームは basetime・member・validtime の3つが揃って初めて同じと見る", () => {
    expect(isKnownEmptyTile(lookup, tileUrl({ frame: `20260924003000/none/${VALIDTIME}` }))).toBe(false);
    expect(isKnownEmptyTile(lookup, tileUrl({ frame: `${BASETIME}/immed0/${VALIDTIME}` }))).toBe(false);
    expect(isKnownEmptyTile(lookup, tileUrl({ frame: `${BASETIME}/none/20260924020000` }))).toBe(false);
  });

  it("網羅範囲の外のタイルは、載っていなくても取りに行く", () => {
    expect(isKnownEmptyTile(lookup, tileUrl({ x: 0, y: 0 }))).toBe(false);
    // 東経146.25度から先（網羅範囲の東端146度の外）
    expect(isKnownEmptyTile(lookup, tileUrl({ x: 29 }))).toBe(false);
  });
});

describe("parseJmaTileElement（要素配下までの前半）", () => {
  it("実URLと{z}/{x}/{y}のテンプレートから同じ前半と要素idを取る", () => {
    const real = parseJmaTileElement(tileUrl());
    const template = parseJmaTileElement(`${HOST}/${BASETIME}/none/${VALIDTIME}/surf/inund/{z}/{x}/{y}.png`);
    expect(real).toEqual({ element: "inund", prefix: `${HOST}/${BASETIME}/none/${VALIDTIME}/surf/inund/` });
    expect(template).toEqual(real);
  });

  it("フレームが変われば前半も変わる", () => {
    expect(parseJmaTileElement(tileUrl({ frame: `${BASETIME}/none/20260924020000` }))?.prefix).not.toBe(
      parseJmaTileElement(tileUrl())?.prefix,
    );
  });

  it("要素の区切りが読めなければ無し", () => {
    expect(parseJmaTileElement("https://example.com/tile/5/28/12.png")).toBeNull();
    expect(parseJmaTileElement(`${HOST}/surf//5/28/12.png`)).toBeNull();
    expect(parseJmaTileElement(`${HOST}/surf/inund`)).toBeNull();
  });
});
