// @vitest-environment node
import { describe, expect, it } from "vitest";

import { jmaDeliveryOf, jmaTileUrlAt } from "@/testing/jmaDeliveries";
import type { JmaTileIndexResponse } from "@/types/route";

import { jmaTilePayload, readJmaTileUrl } from "./jmaDelivery";
import { buildJmaTileIndexLookup, isKnownEmptyTile } from "./jmaTileIndex";

const BASETIME = "20260924000000";
const VALIDTIME = "20260924010000";
// 5/28/12 は東経135〜146度・北緯32〜41度あたり（関東を含む）。
const tileUrl = ({
  element = "inund",
  basetime = BASETIME,
  member = "none",
  validtime = VALIDTIME,
  z = 5,
  x = 28,
  y = 12,
} = {}) =>
  jmaTileUrlAt(
    jmaTilePayload("rasterTile", jmaDeliveryOf(element), { basetime, member, validtime }).tileUrlTemplate,
    z,
    x,
    y,
  );

const JAPAN = { min_longitude: 122, min_latitude: 24, max_longitude: 146, max_latitude: 46 };

function response(elements: Extract<JmaTileIndexResponse, { available: true }>["elements"]): JmaTileIndexResponse {
  return { available: true, coverage: JAPAN, elements };
}

const inundAt = (zooms: Record<string, number[][]>) =>
  response({ inund: { basetime: BASETIME, validtime: VALIDTIME, member: "none", zooms } });

describe("buildJmaTileIndexLookup（在否インデックスの前処理）", () => {
  it("インデックスが無い応答は、使えるインデックス無し", () => {
    expect(buildJmaTileIndexLookup(null)).toBeNull();
    expect(buildJmaTileIndexLookup({ available: false })).toBeNull();
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

  it.each([
    ["網羅範囲内で、載っていないタイルは空", lookup, tileUrl(), true],
    ["載っているタイルは取りに行く", lookup, tileUrl({ y: 13 }), false],
    ["インデックスが無ければ取りに行く", null, tileUrl(), false],
    ["読めないURLは取りに行く", lookup, "https://example.com/tile/5/28/12.png", false],
    ["インデックスに載っていない要素は取りに行く", lookup, tileUrl({ element: "flood" }), false],
    ["フレームが違えば取りに行く", lookup, tileUrl({ validtime: "20260924020000" }), false],
    ["網羅範囲の外は、載っていなくても取りに行く", lookup, tileUrl({ x: 0, y: 0 }), false],
    // 東経146.25度から先（網羅範囲の東端146度の外）
    ["網羅範囲の東端の外も取りに行く", lookup, tileUrl({ x: 29 }), false],
  ])("%s", (_scene, given, url, expected) => {
    expect(isKnownEmptyTile(given, readJmaTileUrl(url))).toBe(expected);
  });
});
