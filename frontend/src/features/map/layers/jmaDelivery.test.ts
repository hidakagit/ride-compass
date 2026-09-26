// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeResponse } from "@/testing/fetchMocks";
import { mapDisplay } from "@/types/generated/mapDisplay";

import {
  fetchJmaPointGeojson,
  fetchJmaTargetTimesFile,
  jmaFramesOf,
  jmaTargetTimesPaths,
  JMA_POINT_VALUE_PROPERTY,
  jmaPlaceholderTileUrl,
  jmaTilePayload,
  parseValidtime,
  type JmaDelivery,
} from "./jmaDelivery";

// テストはnode環境で動くため、配信のオリジンは空（相対パス）になる。
const PROXY = "/api/jma-tile/bosai/jmatile/data";
const DELIVERIES = mapDisplay.weatherElements.flatMap((element): readonly JmaDelivery[] => element.jmaElements);
const withReader = (reader: JmaDelivery["reader"]) => DELIVERIES.find((delivery) => delivery.reader === reader)!;
const fileOf = (delivery: JmaDelivery, index = 0) =>
  `${PROXY}/${delivery.pathGroup}/${delivery.targetTimeFiles[index]}`;

/** 時刻一覧のファイルごとの応答。`undefined`のファイルは500を返す。 */
function stubFiles(files: Record<string, unknown>) {
  const fetchMock = vi.fn(async (url: string) => {
    const body = files[url];
    return body === undefined ? makeResponse({ ok: false, status: 500 }) : makeResponse({ json: async () => body });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.unstubAllGlobals();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const row = (basetime: string, validtime: string, elements: string[], member?: string) => ({
  basetime,
  validtime,
  elements,
  ...(member === undefined ? {} : { member }),
});

describe("読み方: 実況＋予測（nowcast）", () => {
  const delivery = withReader("nowcast");
  const read = (entries: ReturnType<typeof row>[]) => jmaFramesOf(delivery, entries);

  it("その要素の行だけを時刻順に並べ、最新の実況より前（過去）を捨てる", () => {
    expect(
      read([
        row("20260924001000", "20260924002000", [delivery.id]),
        row("20260924001000", "20260924001000", [delivery.id]),
        row("20260924000000", "20260924000000", [delivery.id]),
        row("20260924001500", "20260924001500", ["other"]),
      ]),
    ).toEqual([
      { basetime: "20260924001000", member: "none", validtime: "20260924001000" },
      { basetime: "20260924001000", member: "none", validtime: "20260924002000" },
    ]);
  });

  it("実況が1つも無ければ何も捨てない", () => {
    expect(
      read([
        row("20260924001000", "20260924003000", [delivery.id]),
        row("20260924001000", "20260924002000", [delivery.id]),
      ]).map((frame) => frame.validtime),
    ).toEqual(["20260924002000", "20260924003000"]);
  });
});

describe("読み方: 数値予報のラン（latestFullRun）", () => {
  const delivery = withReader("latestFullRun");
  const read = (entries: ReturnType<typeof row>[]) => jmaFramesOf(delivery, entries);

  it("系列ごとに、有効時刻を複数持つ最新のランだけを使う——単発の中間ラン・古いラン・別の要素の行は使わない", () => {
    const frames = read([
      row("20260924000000", "20260924010000", [delivery.id], "immed"),
      row("20260924000000", "20260924020000", [delivery.id], "immed"),
      row("20260924001000", "20260924001000", [delivery.id], "immed"),
      row("20260923230000", "20260924000000", [delivery.id], "immed"),
      row("20260923230000", "20260924010000", [delivery.id], "immed"),
      row("20260924002000", "20260924011000", ["other"], "immed"),
      row("20260924002000", "20260924021000", ["other"], "immed"),
    ]);
    expect(frames).toEqual([
      { basetime: "20260924000000", member: "immed", validtime: "20260924010000" },
      { basetime: "20260924000000", member: "immed", validtime: "20260924020000" },
    ]);
  });

  it("系列どうしを1本の時刻順につなぎ、同じ有効時刻は新しいランを採る", () => {
    const frames = read([
      row("20260924000000", "20260924080000", [delivery.id], "none"),
      row("20260924000000", "20260924060000", [delivery.id], "none"),
      row("20260924001000", "20260924050000", [delivery.id], "immed"),
      row("20260924001000", "20260924060000", [delivery.id], "immed"),
    ]);
    expect(frames.map((frame) => [frame.validtime, frame.member])).toEqual([
      ["20260924050000", "immed"],
      ["20260924060000", "immed"],
      ["20260924080000", "none"],
    ]);
  });

  it("完全なランが無ければ空", () => {
    expect(read([row("20260924001000", "20260924001000", [delivery.id], "immed")])).toEqual([]);
  });
});

describe("読み方: 現在の単一値（latest）", () => {
  const delivery = withReader("latest");

  it("その要素の最新の1行だけを、系列付きで1コマにする（無ければ空）", () => {
    expect(
      jmaFramesOf(delivery, [
        row("20260924000000", "20260924000000", [delivery.id, "other"], "none"),
        row("20260924001000", "20260924001000", [delivery.id], "immed"),
        row("20260924002000", "20260924002000", ["other"], "none"),
      ]),
    ).toEqual([{ basetime: "20260924001000", member: "immed", validtime: "20260924001000" }]);
    expect(jmaFramesOf(delivery, [row("20260924002000", "20260924002000", ["other"], "none")])).toEqual([]);
  });
});

describe("時刻一覧のファイル", () => {
  it("配列でない応答は形式の誤りとして失敗に数える", async () => {
    const delivery = DELIVERIES[0];
    stubFiles({ [fileOf(delivery)]: {} });
    await expect(fetchJmaTargetTimesFile(jmaTargetTimesPaths(delivery)[0], "要素")).rejects.toThrow(
      "要素の時刻一覧の形式が想定と異なります",
    );
  });
});

describe("コマのURL", () => {
  const frame = { basetime: "20260924000000", member: "immed", validtime: "20260924010000" };
  const delivery = DELIVERIES[0];

  it("配信元のパス構造 .../data/<系統>/<basetime>/<member>/<validtime>/surf/<要素>/ に、描き方の拡張子を付ける", () => {
    expect(jmaTilePayload("vectorTile", delivery, frame)).toEqual({
      kind: "vectorTile",
      tileUrlTemplate: `${PROXY}/${delivery.pathGroup}/20260924000000/immed/20260924010000/surf/${delivery.id}/{z}/{x}/{y}.pbf`,
    });
    expect(jmaTilePayload("rasterTile", delivery, frame)).toMatchObject({
      kind: "rasterTile",
      tileUrlTemplate: expect.stringMatching(/\{z\}\/\{x\}\/\{y\}\.png$/),
    });
  });

  it("中身が届く前の仮のURLは、タイルで描く要素のどれも実在しない時刻を指し、描き方の拡張子を持つ", () => {
    const tileElements = mapDisplay.weatherElements.filter(
      (element) => (element.kind === "rasterTile" || element.kind === "vectorTile") && element.jmaElements.length > 0,
    );
    expect(tileElements).not.toHaveLength(0);
    for (const element of tileElements) {
      const extension = element.kind === "vectorTile" ? "pbf" : "png";
      expect(
        jmaPlaceholderTileUrl(element).endsWith(
          `/00000000000000/none/00000000000000/surf/${element.jmaElements[0]!.id}/{z}/{x}/{y}.${extension}`,
        ),
      ).toBe(true);
    }
  });

  it("地点はそのコマの要素配下のGeoJSONを取り、どの地点にも記号の大きさを決める値を足す（元の属性は残す）", async () => {
    const fetchMock = vi.fn<(url: string) => Promise<ReturnType<typeof makeResponse>>>(async () =>
      makeResponse({
        json: async () => ({
          type: "FeatureCollection",
          features: [
            { type: "Feature", geometry: { type: "Point", coordinates: [139, 35] }, properties: { type: 1 } },
            { type: "Feature", geometry: { type: "Point", coordinates: [140, 36] }, properties: null },
          ],
        }),
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const geojson = await fetchJmaPointGeojson(delivery, frame, "地点");
    expect(fetchMock.mock.calls[0][0]).toBe(
      `${PROXY}/${delivery.pathGroup}/20260924000000/immed/20260924010000/surf/${delivery.id}/data.geojson?id=${delivery.id}`,
    );
    expect(geojson.features.map((feature) => feature.properties)).toEqual([
      { type: 1, [JMA_POINT_VALUE_PROPERTY]: 1 },
      { [JMA_POINT_VALUE_PROPERTY]: 1 },
    ]);
  });

  it("地点の取得の失敗はそのまま投げる（表示しないかは呼び出し側が決める）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => makeResponse({ ok: false, status: 503 })),
    );
    await expect(fetchJmaPointGeojson(delivery, frame, "地点")).rejects.toThrow("地点");
  });
});

describe("コマの時刻", () => {
  it("validtimeは協定世界時の YYYYMMDDHHmmss", () => {
    expect(parseValidtime("20260923153000").toISOString()).toBe("2026-09-23T15:30:00.000Z");
  });
});
