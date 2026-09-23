// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeResponse } from "@/testing/fetchMocks";
import { mapDisplay } from "@/types/generated/mapDisplay";

import {
  fetchJmaNowcastFrames,
  fetchJmaTargetTimes,
  jmaDelivery,
  jmaElementUrl,
  jmaFrameTimeline,
  jmaPlaceholderTileUrl,
  jmaTilePayload,
  parseValidtime,
  trimToCurrentAndFuture,
  type JmaNowcastFrame,
} from "./jmaNowcastFrames";

// テストはnode環境で動くため、配信のオリジンは空（相対パス）になる。
const PROXY = "/api/jma-tile/bosai/jmatile/data";
const THUNDER = jmaDelivery("disaster/thunder").id;
const LIDEN = jmaDelivery("disaster/liden").id;
const RAIN = jmaDelivery("precipitationNowcast/main").id;

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

const row = (basetime: string, validtime: string, elements: string[]) => ({ basetime, validtime, elements });

describe("fetchJmaNowcastFrames（要素の時刻一覧）", () => {
  it("その要素のタイルがある行だけを、時刻順に、予測かどうかを付けて返す", async () => {
    stubFiles({
      [`${PROXY}/nowc/targetTimes_N3.json`]: [
        row("20260924001000", "20260924002000", [THUNDER, LIDEN]),
        row("20260924001000", "20260924001000", [THUNDER, LIDEN]),
        row("20260924000500", "20260924000500", [LIDEN]),
      ],
    });
    expect(await fetchJmaNowcastFrames("disaster/thunder", "雷")).toEqual([
      { basetime: "20260924001000", validtime: "20260924001000", isForecast: false },
      { basetime: "20260924001000", validtime: "20260924002000", isForecast: true },
    ]);
    expect((await fetchJmaNowcastFrames("disaster/liden", "落雷")).map((frame) => frame.validtime)).toEqual([
      "20260924000500",
      "20260924001000",
      "20260924002000",
    ]);
  });
});

describe("fetchJmaTargetTimes（時刻一覧のファイル）", () => {
  const N1 = `${PROXY}/nowc/targetTimes_N1.json`;
  const N2 = `${PROXY}/nowc/targetTimes_N2.json`;
  const observed = row("20260924000000", "20260924000000", [RAIN]);
  const forecast = row("20260924000000", "20260924001000", [RAIN]);

  it("複数のファイルに分かれる要素は、宣言の順に全ファイルの行をつなげる", async () => {
    stubFiles({ [N1]: [observed], [N2]: [forecast] });
    expect(await fetchJmaTargetTimes(jmaDelivery("precipitationNowcast/main"), "降水")).toEqual([observed, forecast]);
  });

  it("一部のファイルだけ取れなくても残りを返し、全部取れないときだけ投げる", async () => {
    stubFiles({ [N2]: [forecast] });
    expect(await fetchJmaTargetTimes(jmaDelivery("precipitationNowcast/main"), "降水")).toEqual([forecast]);

    stubFiles({});
    await expect(fetchJmaTargetTimes(jmaDelivery("precipitationNowcast/main"), "降水")).rejects.toThrow(
      "降水の時刻一覧",
    );
  });

  it("配列でない応答は形式の誤りとして失敗に数える", async () => {
    stubFiles({ [N1]: { unexpected: true } });
    await expect(fetchJmaTargetTimes(jmaDelivery("precipitationNowcast/main"), "降水")).rejects.toThrow(
      "降水の時刻一覧の形式が想定と異なります",
    );
  });

  it("同じファイルを同時に取りに行く呼び出しは往復を1回に畳み、終わった後は取り直す", async () => {
    const fetchMock = stubFiles({
      [`${PROXY}/nowc/targetTimes_N3.json`]: [row("20260924000000", "20260924000000", [THUNDER])],
    });
    await Promise.all([
      fetchJmaNowcastFrames("disaster/thunder", "雷"),
      fetchJmaNowcastFrames("disaster/liden", "落雷"),
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await fetchJmaNowcastFrames("disaster/thunder", "雷");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("失敗した取得も共有を解き、次の呼び出しは取り直す", async () => {
    const fetchMock = stubFiles({});
    await expect(fetchJmaNowcastFrames("disaster/thunder", "雷")).rejects.toThrow();
    await expect(fetchJmaNowcastFrames("disaster/thunder", "雷")).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("タイルのURL", () => {
  const time = { basetime: "20260924000000", member: "immed", validtime: "20260924010000" };

  it("配信元のパス構造 .../data/<系統>/<basetime>/<member>/<validtime>/surf/<要素>/ に、描き方の拡張子を付ける", () => {
    const risk = jmaDelivery("disaster/flood");
    expect(jmaTilePayload("disaster/flood", time)).toEqual({
      kind: "vectorTile",
      tileUrlTemplate: `${PROXY}/${risk.pathGroup}/20260924000000/immed/20260924010000/surf/${risk.id}/{z}/{x}/{y}.pbf`,
    });
    expect(jmaTilePayload("disaster/thunder", time)).toMatchObject({
      kind: "rasterTile",
      tileUrlTemplate: expect.stringMatching(/\{z\}\/\{x\}\/\{y\}\.png$/),
    });
  });

  it("時刻の段ごとに別の配信要素から届く", () => {
    const later = jmaDelivery("precipitationNowcast/main", 1);
    expect(later.id).not.toBe(RAIN);
    expect(jmaTilePayload("precipitationNowcast/main", time, 1)).toMatchObject({
      tileUrlTemplate: expect.stringContaining(
        `/${later.pathGroup}/20260924000000/immed/20260924010000/surf/${later.id}/`,
      ),
    });
  });

  it("GeoJSON等のタイル以外も、同じ要素配下のパスに続けて組み立てる", () => {
    expect(jmaElementUrl({ group: "nowc", element: LIDEN, ...time, member: "none" }, `data.geojson?id=${LIDEN}`)).toBe(
      `${PROXY}/nowc/20260924000000/none/20260924010000/surf/${LIDEN}/data.geojson?id=${LIDEN}`,
    );
  });

  it("中身が届く前の仮のURLは、タイルで描く要素のどれも実在しない時刻を指し、描き方の拡張子を持つ", () => {
    const tileElements = mapDisplay.weatherElements.filter(
      (element) => (element.kind === "rasterTile" || element.kind === "vectorTile") && element.jmaElements.length > 0,
    ) as Parameters<typeof jmaPlaceholderTileUrl>[0][];
    expect(tileElements).not.toHaveLength(0);
    for (const element of tileElements) {
      const extension = element.kind === "vectorTile" ? "pbf" : "png";
      expect(
        jmaPlaceholderTileUrl(element).endsWith(
          `/00000000000000/none/00000000000000/surf/${element.jmaElements[0].id}/{z}/{x}/{y}.${extension}`,
        ),
      ).toBe(true);
    }
  });
});

describe("フレームの時刻", () => {
  const frame = (validtime: string, isForecast: boolean): JmaNowcastFrame => ({
    basetime: "20260924000000",
    validtime,
    isForecast,
  });

  it("validtimeは協定世界時の YYYYMMDDHHmmss", () => {
    expect(parseValidtime("20260923153000").toISOString()).toBe("2026-09-23T15:30:00.000Z");
  });

  it("タイムラインのコマは、時刻とフレームそのもの", () => {
    const frames = [frame("20260924000000", false), frame("20260924001000", true)];
    expect(jmaFrameTimeline(frames)).toEqual([
      { time: new Date("2026-09-24T00:00:00Z"), ref: frames[0] },
      { time: new Date("2026-09-24T00:10:00Z"), ref: frames[1] },
    ]);
  });

  it("最新の実況より前（過去）を切り捨て、先頭を「今」にする", () => {
    const frames = [frame("20260923235000", false), frame("20260924000000", false), frame("20260924001000", true)];
    expect(trimToCurrentAndFuture(frames)).toEqual(frames.slice(1));
  });

  it("実況が1つも無ければ何も切り捨てない", () => {
    const frames = [frame("20260924001000", true), frame("20260924002000", true)];
    expect(trimToCurrentAndFuture(frames)).toEqual(frames);
    expect(trimToCurrentAndFuture([])).toEqual([]);
  });
});
