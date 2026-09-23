// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeResponse } from "@/testing/fetchMocks";
import type { WindGridPoint } from "@/types/weather";

import { jmaDelivery, type JmaNowcastFrame } from "./jmaNowcastFrames";
import {
  fetchRasrfFrames,
  PRECIPITATION_COLOR_STOPS,
  PRECIPITATION_INTENSITY_LEVELS,
  precipitationFrames,
  precipitationRenderPayload,
  type RasrfFrame,
} from "./precipitationNowcast";

const SHORT_RANGE = jmaDelivery("precipitationNowcast/main", 1);
const RAINBAND = jmaDelivery("precipitationNowcast/linearRainband").id;
const SHORT_RANGE_FILE = `/api/jma-tile/bosai/jmatile/data/${SHORT_RANGE.pathGroup}/${SHORT_RANGE.targetTimeFiles[0]}`;

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubShortRange(rows: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url === SHORT_RANGE_FILE ? makeResponse({ json: async () => rows }) : makeResponse({ ok: false, status: 404 }),
    ),
  );
}

const entry = (basetime: string, validtime: string, member: string, elements = [SHORT_RANGE.id]) => ({
  basetime,
  validtime,
  member,
  elements,
});

describe("fetchRasrfFrames（降水短時間予報の時刻一覧）", () => {
  it("系列ごとに、validtimeを複数持つ最新のラン（完全な予報）だけを使う——単発の中間ランは使わない", async () => {
    stubShortRange([
      entry("20260924000000", "20260924010000", "immed"),
      entry("20260924000000", "20260924020000", "immed"),
      // 後から来た中間ラン（validtime 1つだけ）
      entry("20260924001000", "20260924001000", "immed"),
      // 古い完全なラン
      entry("20260923230000", "20260924000000", "immed"),
      entry("20260923230000", "20260924010000", "immed"),
    ]);
    expect(await fetchRasrfFrames()).toEqual([
      { basetime: "20260924000000", validtime: "20260924010000", member: "immed", isForecast: true },
      { basetime: "20260924000000", validtime: "20260924020000", member: "immed", isForecast: true },
    ]);
  });

  it("同じファイルに混ざる別の要素（線状降水帯）の行は数えない", async () => {
    stubShortRange([
      entry("20260924000000", "20260924010000", "immed"),
      entry("20260924000000", "20260924020000", "immed"),
      entry("20260924001000", "20260924011000", "immed", [RAINBAND]),
      entry("20260924001000", "20260924021000", "immed", [RAINBAND]),
    ]);
    expect((await fetchRasrfFrames()).map((frame) => frame.basetime)).toEqual(["20260924000000", "20260924000000"]);
  });

  it("直近（immed）と先（none）の2系列を1本の時刻順につなげ、同じ時刻は詳細な直近を採る", async () => {
    stubShortRange([
      entry("20260924000000", "20260924080000", "none"),
      entry("20260924000000", "20260924060000", "none"),
      entry("20260924001000", "20260924050000", "immed"),
      entry("20260924001000", "20260924060000", "immed"),
    ]);
    expect((await fetchRasrfFrames()).map((frame) => [frame.validtime, frame.member])).toEqual([
      ["20260924050000", "immed"],
      ["20260924060000", "immed"],
      ["20260924080000", "none"],
    ]);
  });

  it("完全なランが無ければ空", async () => {
    stubShortRange([entry("20260924001000", "20260924001000", "immed")]);
    expect(await fetchRasrfFrames()).toEqual([]);
  });
});

const nowcast = (validtime: string, isForecast = true): JmaNowcastFrame => ({
  basetime: "20260924000000",
  validtime,
  isForecast,
});
const rasrf = (validtime: string, member = "immed"): RasrfFrame => ({
  basetime: "20260924000000",
  validtime,
  member,
  isForecast: true,
});
/** 延長予報の格子（日本時間・オフセット無しの時刻）。 */
const gridPoint = (times: string[], precipitation: (number | null)[], latitude = 35, longitude = 139): WindGridPoint =>
  ({
    latitude,
    longitude,
    times,
    wind_speed_ms: times.map(() => 1),
    wind_direction_deg: times.map(() => 0),
    precipitation_mm: precipitation,
  }) as WindGridPoint;

describe("precipitationFrames（3段を1本のタイムラインへ）", () => {
  it("ナウキャスト→短時間予報→延長予報の順に、前の段の最後より後の時刻だけを継ぐ", () => {
    const frames = precipitationFrames(
      [nowcast("20260924000000", false), nowcast("20260924010000")],
      [rasrf("20260924010000"), rasrf("20260924020000")],
      // 日本時間 11:00 = 協定世界時 02:00（短時間予報の最後と同時刻）、12:00 = 03:00
      [gridPoint(["2026-09-24T11:00", "2026-09-24T12:00"], [0, 1])],
    );
    expect(frames.map((frame) => [frame.time.toISOString(), frame.ref.source])).toEqual([
      ["2026-09-24T00:00:00.000Z", "nowcast"],
      ["2026-09-24T01:00:00.000Z", "nowcast"],
      ["2026-09-24T02:00:00.000Z", "shortRange"],
      ["2026-09-24T03:00:00.000Z", "extended"],
    ]);
    expect(frames[3].ref).toEqual({ source: "extended", index: 1 });
  });

  it("短時間予報が取れていなければ、ナウキャストの直後から延長予報を継ぐ", () => {
    const frames = precipitationFrames(
      [nowcast("20260924000000", false)],
      [],
      [gridPoint(["2026-09-24T09:00", "2026-09-24T10:00"], [0, 1])],
    );
    expect(frames.map((frame) => frame.ref.source)).toEqual(["nowcast", "extended"]);
  });

  it("どの段も無ければ空", () => {
    expect(precipitationFrames([], [], [])).toEqual([]);
  });
});

describe("precipitationRenderPayload（コマの描き方）", () => {
  it("ナウキャスト・短時間予報は配信元のタイル（短時間予報だけ系列がURLに入る）", () => {
    const [now, short] = precipitationFrames([nowcast("20260924000000", false)], [rasrf("20260924020000", "none")], []);
    expect(precipitationRenderPayload([], 0.1, now.ref)).toMatchObject({
      kind: "rasterTile",
      tileUrlTemplate: expect.stringContaining("/20260924000000/none/20260924000000/surf/"),
    });
    expect(precipitationRenderPayload([], 0.1, short.ref)).toMatchObject({
      kind: "rasterTile",
      tileUrlTemplate: expect.stringContaining(`/20260924000000/none/20260924020000/surf/${SHORT_RANGE.id}/`),
    });
  });

  it("延長予報は、描く格子の各点を中心とする正方形をその時刻の降水量で塗る（欠けた点は飛ばす）", () => {
    const grid = [gridPoint(["2026-09-24T12:00"], [2.5], 35, 139), gridPoint(["2026-09-24T12:00"], [null], 35.1, 139)];
    const payload = precipitationRenderPayload(grid, 0.1, { source: "extended", index: 0 });
    expect(payload.kind).toBe("gridFill");
    const { features } = payload.kind === "gridFill" ? payload.geojson : { features: [] };
    expect(features).toHaveLength(1);
    expect(features[0].properties).toEqual({ mmPerHour: 2.5 });
    expect(features[0].geometry).toMatchObject({ type: "Polygon" });
  });
});

describe("降水強度の凡例", () => {
  it("色の段1つにつき1行、同じ順・同じ色で、帯の境界の値を名乗る", () => {
    expect(PRECIPITATION_INTENSITY_LEVELS.map((level) => level.color)).toEqual(
      PRECIPITATION_COLOR_STOPS.map((stop) => stop.color),
    );
    PRECIPITATION_INTENSITY_LEVELS.forEach((level, i) => {
      const next = PRECIPITATION_COLOR_STOPS[i + 1];
      if (next) expect(level.label).toContain(`${next.mmPerHour}mm/h`);
    });
  });
});
