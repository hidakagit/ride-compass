// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchNowcastFrames,
  parseValidtime,
  precipitationFrames,
  precipitationRenderPayload,
  trimToCurrentAndFuture,
  PRECIPITATION_COLOR_STOPS,
  PRECIPITATION_INTENSITY_LEVELS,
} from "./precipitationNowcast";
import { parseJstTime, WIND_GRID_SPACING_DEG } from "./windLayer";
import type { WindGridPoint } from "@/types/weather";

const N1 = [
  { basetime: "20260820030000", validtime: "20260820030000" },
  { basetime: "20260820025500", validtime: "20260820025500" },
];
const N2 = [
  { basetime: "20260820030000", validtime: "20260820030500" },
  { basetime: "20260820030000", validtime: "20260820031000" },
];

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body, headers: new Headers() };
}

describe("precipitationNowcast", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetchNowcastFramesは実況(N1)・予測(N2)を合わせてvalidtime昇順に並べ、isForecastを正しく付与する", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("N1")) return Promise.resolve(jsonResponse(N1));
      return Promise.resolve(jsonResponse(N2));
    });
    vi.stubGlobal("fetch", fetchMock);

    const frames = await fetchNowcastFrames();

    expect(frames.map((f) => f.validtime)).toEqual([
      "20260820025500",
      "20260820030000",
      "20260820030500",
      "20260820031000",
    ]);
    expect(frames.map((f) => f.isForecast)).toEqual([false, false, true, true]);
  });

  it("片方(N1)の取得に失敗しても、もう片方(N2)だけの部分的な時系列を返す", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("N1")) return Promise.resolve(jsonResponse(null, false, 500));
      return Promise.resolve(jsonResponse(N2));
    });
    vi.stubGlobal("fetch", fetchMock);

    const frames = await fetchNowcastFrames();

    expect(frames.map((f) => f.validtime)).toEqual(["20260820030500", "20260820031000"]);
    expect(frames.every((f) => f.isForecast)).toBe(true);
  });

  it("両方とも取得に失敗した場合は例外を投げる", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse(null, false, 500)));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchNowcastFrames()).rejects.toThrow();
  });

  describe("trimToCurrentAndFuture（実機フィードバック「過去の風、雨を気にすることはアプリの性質上ない、デフォルト位置を左端に」）", () => {
    function frame(validtime: string, isForecast: boolean) {
      return { basetime: "a", validtime, isForecast };
    }

    it("「現在」より前の実況フレームをすべて切り捨て、「現在」がindex 0（左端）に来るようにする", () => {
      const frames = [
        frame("1", false),
        frame("2", false),
        frame("3", false),
        frame("4", true),
        frame("5", true),
      ];
      const result = trimToCurrentAndFuture(frames);
      expect(result.map((f) => f.validtime)).toEqual(["3", "4", "5"]);
      expect(result.filter((f) => !f.isForecast)).toEqual([frame("3", false)]);
    });

    it("実況フレームが「現在」の1件しか無ければ何も切り詰めない", () => {
      const frames = [frame("1", false), frame("2", true), frame("3", true)];
      expect(trimToCurrentAndFuture(frames)).toEqual(frames);
    });

    it("空配列を渡すと空配列を返す", () => {
      expect(trimToCurrentAndFuture([])).toEqual([]);
    });
  });

  it("parseValidtimeはUTCのvalidtimeをDateへ変換する", () => {
    // 20260820030000 (UTC) = JST 12:00
    expect(parseValidtime("20260820030000").toISOString()).toBe("2026-08-20T03:00:00.000Z");
  });

  describe("PRECIPITATION_COLOR_STOPS", () => {
    it("mm/hは単調増加する", () => {
      for (let i = 1; i < PRECIPITATION_COLOR_STOPS.length; i++) {
        expect(PRECIPITATION_COLOR_STOPS[i].mmPerHour).toBeGreaterThan(PRECIPITATION_COLOR_STOPS[i - 1].mmPerHour);
      }
    });
  });

  describe("PRECIPITATION_INTENSITY_LEVELS", () => {
    it("数値・色はPRECIPITATION_COLOR_STOPSと食い違わない（単一の情報源）", () => {
      expect(PRECIPITATION_INTENSITY_LEVELS).toHaveLength(PRECIPITATION_COLOR_STOPS.length);
      expect(PRECIPITATION_INTENSITY_LEVELS[0].color).toBe(PRECIPITATION_COLOR_STOPS[0].color);
      expect(PRECIPITATION_INTENSITY_LEVELS.at(-1)?.color).toBe(PRECIPITATION_COLOR_STOPS.at(-1)?.color);
      expect(PRECIPITATION_INTENSITY_LEVELS[1].label).toContain(`${PRECIPITATION_COLOR_STOPS[1].mmPerHour}`);
    });
  });

  describe("precipitationFrames（T183: ナウキャスト+延長予報のデータ取得層での統合、dynamicWeather.tsの共通フレーム列へ変換）", () => {
    function nowcastFrame(validtime: string, isForecast: boolean) {
      return { basetime: "a", validtime, isForecast };
    }
    function extendedGrid(times: readonly string[]): WindGridPoint[] {
      return [
        {
          latitude: 35.68,
          longitude: 139.77,
          times: [...times],
          wind_speed_ms: times.map(() => 0),
          wind_direction_deg: times.map(() => 0),
          precipitation_mm: times.map(() => 1),
        },
      ];
    }

    it("ナウキャスト(実況/予測)を先頭へ、延長予報を後ろへ並べ、それぞれ正しいref・timeを付ける", () => {
      // 20260820030000 UTC = 12:00 JST。ナウキャストは実況1件・予測1件（12:00, 12:05 JST）。
      const nowcastFrames = [nowcastFrame("20260820030000", false), nowcastFrame("20260820030500", true)];
      // 延長側（風と共通の格子点マップ由来）は13:00, 14:00 JST（JSTのオフセット無し表記）。
      const frames = precipitationFrames(nowcastFrames, extendedGrid(["2026-08-20T13:00", "2026-08-20T14:00"]));

      expect(frames).toEqual([
        { time: parseValidtime("20260820030000"), ref: { source: "nowcast", index: 0 } },
        { time: parseValidtime("20260820030500"), ref: { source: "nowcast", index: 1 } },
        { time: parseJstTime("2026-08-20T13:00"), ref: { source: "extended", index: 0 } },
        { time: parseJstTime("2026-08-20T14:00"), ref: { source: "extended", index: 1 } },
      ]);
    });

    it("ナウキャストの最終フレーム以前の延長予報時刻は除外する(近い将来の二重表示を避ける)", () => {
      // ナウキャストの最終フレームは12:05 JST。延長側の12:00は最終フレームより前なので除外、
      // 13:00は最終フレームより後なので採用される。
      const nowcastFrames = [nowcastFrame("20260820030000", false), nowcastFrame("20260820030500", true)];
      const frames = precipitationFrames(nowcastFrames, extendedGrid(["2026-08-20T12:00", "2026-08-20T13:00"]));

      expect(frames.filter((f) => f.ref.source === "extended")).toEqual([
        { time: parseJstTime("2026-08-20T13:00"), ref: { source: "extended", index: 1 } },
      ]);
    });

    it("ナウキャストが空でも延長予報だけの時系列を返す", () => {
      const frames = precipitationFrames([], extendedGrid(["2026-08-20T13:00"]));
      expect(frames).toEqual([{ time: parseJstTime("2026-08-20T13:00"), ref: { source: "extended", index: 0 } }]);
    });

    it("両方空なら空配列を返す", () => {
      expect(precipitationFrames([], [])).toEqual([]);
    });
  });

  describe("precipitationRenderPayload（アイコンは1つ、内部は時間によって使い分ける。sourceでrasterTile/gridFillを切り替える）", () => {
    const nowcastFrames = [{ basetime: "20260820030000", validtime: "20260820030500", isForecast: true }];
    const extendedGrid: WindGridPoint[] = [
      {
        latitude: 35.68,
        longitude: 139.77,
        times: ["t0", "t1"],
        wind_speed_ms: [0, 0],
        wind_direction_deg: [0, 0],
        precipitation_mm: [0.5, 3.2],
      },
      {
        latitude: 36.0,
        longitude: 140.0,
        times: ["t0", "t1"],
        wind_speed_ms: [0, 0],
        wind_direction_deg: [0, 0],
        precipitation_mm: [0, 12.5],
      },
    ];

    it("source=nowcastならkind=rasterTileで、basetime/validtimeを埋め込んだタイルURLを返す", () => {
      const payload = precipitationRenderPayload(nowcastFrames, extendedGrid, WIND_GRID_SPACING_DEG, {
        source: "nowcast",
        index: 0,
      });
      expect(payload).toEqual({
        kind: "rasterTile",
        tileUrlTemplate: "https://www.jma.go.jp/bosai/jmatile/data/nowc/20260820030000/none/20260820030500/surf/hrpns/{z}/{x}/{y}.png",
      });
    });

    it("source=nowcastでも該当indexのフレームが無ければundefinedを返す", () => {
      expect(
        precipitationRenderPayload(nowcastFrames, extendedGrid, WIND_GRID_SPACING_DEG, { source: "nowcast", index: 5 })
      ).toBeUndefined();
    });

    it("source=extendedならkind=gridFillで、指定indexの降水量からGeoJSON Polygonを構築する", () => {
      const payload = precipitationRenderPayload(nowcastFrames, extendedGrid, WIND_GRID_SPACING_DEG, {
        source: "extended",
        index: 1,
      });
      expect(payload?.kind).toBe("gridFill");
      if (payload?.kind !== "gridFill") throw new Error("unreachable");
      expect(payload.geojson.features).toHaveLength(2);
      expect(payload.geojson.features[0].properties?.mmPerHour).toBe(3.2);
      expect(payload.geojson.features[1].properties?.mmPerHour).toBe(12.5);
      const geometry = payload.geojson.features[0].geometry;
      if (geometry.type !== "Polygon") throw new Error("unreachable");
      expect(geometry.coordinates[0][0]).toEqual([139.77 - WIND_GRID_SPACING_DEG / 2, 35.68 - WIND_GRID_SPACING_DEG / 2]);
    });

    it("source=extendedでextendedGridが空ならundefinedを返す", () => {
      expect(precipitationRenderPayload(nowcastFrames, [], WIND_GRID_SPACING_DEG, { source: "extended", index: 0 })).toBeUndefined();
    });

    it("source=extendedで値が欠損している格子点はスキップする(欠損に頑健)", () => {
      const payload = precipitationRenderPayload(nowcastFrames, extendedGrid, WIND_GRID_SPACING_DEG, {
        source: "extended",
        index: 5,
      });
      expect(payload?.kind).toBe("gridFill");
      if (payload?.kind !== "gridFill") throw new Error("unreachable");
      expect(payload.geojson.features).toHaveLength(0);
    });
  });
});
