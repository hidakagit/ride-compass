// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  buildJmaTileIndexLookup,
  isKnownEmptyTile,
  parseJmaTileUrl,
  type JmaTileIndexResponse,
} from "@/components/Map/jmaTileIndex";

const BASE = "https://example.test/api/jma-tile/bosai/jmatile/data/risk";
const BT = "20260907025000";
// 関東本土（backendのWIND_GRID_BBOX）。z10の(909,403)は東京付近。
const COVERAGE = {
  min_longitude: 138.35,
  min_latitude: 34.85,
  max_longitude: 140.95,
  max_latitude: 37.2,
};

function response(overrides: Partial<JmaTileIndexResponse> = {}): JmaTileIndexResponse {
  return {
    available: true,
    coverage: COVERAGE,
    elements: {
      rain_mesh: { basetime: BT, validtime: BT, member: "immed0", zooms: { "10": [[909, 403]] } },
    },
    ...overrides,
  };
}

const tileUrl = (element: string, z: number, x: number, y: number, basetime = BT) =>
  `${BASE}/${basetime}/immed0/${basetime}/surf/${element}/${z}/${x}/${y}.png`;

describe("parseJmaTileUrl", () => {
  it("要素id・basetime・タイル座標を取り出す", () => {
    expect(parseJmaTileUrl(tileUrl("rain_mesh", 10, 909, 403))).toEqual({
      element: "rain_mesh",
      basetime: BT,
      z: 10,
      x: 909,
      y: 403,
    });
  });

  it("ベクタタイル（.pbf）も解釈する", () => {
    expect(parseJmaTileUrl(`${BASE}/${BT}/immed0/${BT}/surf/flood/10/909/403.pbf`)?.element).toBe("flood");
  });

  it.each([
    "https://example.test/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json",
    "https://example.test/api/region/road-surface-tiles/14/14551/6447.pbf",
    "https://example.test/api/jma-tile/bosai/jmatile/data/nowc/20260907/none/20260907/surf/liden/data.geojson?id=liden",
  ])("タイル以外は解釈しない: %s", (url) => {
    expect(parseJmaTileUrl(url)).toBeNull();
  });
});

describe("buildJmaTileIndexLookup", () => {
  it("available:false はインデックス無しとして扱う", () => {
    expect(buildJmaTileIndexLookup({ available: false })).toBeNull();
  });

  it("basetimeを持たない要素は載せない（世代を照合できないため）", () => {
    const lookup = buildJmaTileIndexLookup(
      response({
        elements: {
          rain_mesh: { basetime: null, validtime: null, member: "none", zooms: {} },
        },
      }),
    );

    expect(lookup).toBeNull();
  });

  it("座標をSetへ展開する", () => {
    const lookup = buildJmaTileIndexLookup(response());

    expect(lookup?.elements.get("rain_mesh")?.present.has("10/909/403")).toBe(true);
  });
});

describe("isKnownEmptyTile", () => {
  const lookup = buildJmaTileIndexLookup(response());

  it("インデックスに載っているタイルは空ではない（取りに行く）", () => {
    expect(isKnownEmptyTile(lookup, tileUrl("rain_mesh", 10, 909, 403))).toBe(false);
  });

  it("網羅範囲内でインデックスに無いタイルは空と判定する（省く）", () => {
    expect(isKnownEmptyTile(lookup, tileUrl("rain_mesh", 10, 910, 403))).toBe(true);
  });

  // 以下はいずれも「判断がつかない」ケース。取りこぼしを避けるため必ず取りに行く。
  it("インデックス未取得なら取りに行く", () => {
    expect(isKnownEmptyTile(null, tileUrl("rain_mesh", 10, 910, 403))).toBe(false);
  });

  it("basetimeが違えば取りに行く（インデックスが古い/新しい）", () => {
    expect(isKnownEmptyTile(lookup, tileUrl("rain_mesh", 10, 910, 403, "20260907030000"))).toBe(false);
  });

  it("インデックスに無い要素は取りに行く", () => {
    expect(isKnownEmptyTile(lookup, tileUrl("land", 10, 910, 403))).toBe(false);
  });

  it("網羅範囲の外は取りに行く", () => {
    // 北海道付近のz10タイル（coverage=関東本土の外）。
    expect(isKnownEmptyTile(lookup, tileUrl("rain_mesh", 10, 916, 385))).toBe(false);
  });

  it("タイル以外のURLは対象外", () => {
    expect(isKnownEmptyTile(lookup, `${BASE}/targetTimes.json`)).toBe(false);
  });
});
