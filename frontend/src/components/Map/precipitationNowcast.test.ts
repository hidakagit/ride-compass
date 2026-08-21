// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildCombinedPrecipitationFrames,
  fetchNowcastFrames,
  formatNowcastFrameTime,
  latestObservedFrameIndex,
  nearestCombinedPrecipitationFrameIndex,
  nearestFrameIndexByTime,
  nowcastTileUrlTemplate,
  parseValidtime,
  precipitationGridToFeatureCollection,
  trimToCurrentAndFuture,
  PRECIPITATION_COLOR_STOPS,
  PRECIPITATION_INTENSITY_LEVELS,
} from "./precipitationNowcast";
import { parseJstTime } from "./windLayer";
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
  return { ok, status, json: async () => body };
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

  it("latestObservedFrameIndexは実況(isForecast=false)の最後のindexを返す", () => {
    const frames = [
      { basetime: "a", validtime: "1", isForecast: false },
      { basetime: "a", validtime: "2", isForecast: false },
      { basetime: "a", validtime: "3", isForecast: true },
      { basetime: "a", validtime: "4", isForecast: true },
    ];
    expect(latestObservedFrameIndex(frames)).toBe(1);
  });

  it("latestObservedFrameIndexは実況フレームが無ければ末尾のindexを返す", () => {
    const frames = [
      { basetime: "a", validtime: "1", isForecast: true },
      { basetime: "a", validtime: "2", isForecast: true },
    ];
    expect(latestObservedFrameIndex(frames)).toBe(1);
  });

  it("latestObservedFrameIndexは空配列に対して0を返す", () => {
    expect(latestObservedFrameIndex([])).toBe(0);
  });

  it("formatNowcastFrameTimeはUTCのvalidtimeをJSTのHH:mmへ変換する", () => {
    // 20260820030000 (UTC) = JST 12:00
    expect(formatNowcastFrameTime("20260820030000")).toBe("12:00");
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
      expect(latestObservedFrameIndex(result)).toBe(0);
    });

    it("実況フレームが「現在」の1件しか無ければ何も切り詰めない", () => {
      const frames = [frame("1", false), frame("2", true), frame("3", true)];
      expect(trimToCurrentAndFuture(frames)).toEqual(frames);
    });

    it("空配列を渡すと空配列を返す", () => {
      expect(trimToCurrentAndFuture([])).toEqual([]);
    });
  });

  describe("nearestFrameIndexByTime（下部バー2本の時刻連動、実機フィードバック「同じ日時を示した状態で連動させ」）", () => {
    function frame(validtime: string, isForecast: boolean) {
      return { basetime: "a", validtime, isForecast };
    }
    // UTCのvalidtime。1分刻みで3フレーム。
    const frames = [frame("20260820030000", false), frame("20260820030100", false), frame("20260820030200", true)];

    it("対象時刻に最も近いフレームのindexを返す", () => {
      expect(nearestFrameIndexByTime(frames, new Date("2026-08-20T03:00:40Z"))).toBe(1);
      expect(nearestFrameIndexByTime(frames, new Date("2026-08-20T03:01:20Z"))).toBe(1);
    });

    it("範囲外の対象時刻は最も近い端のindexへクランプされる", () => {
      expect(nearestFrameIndexByTime(frames, new Date("2026-08-20T00:00:00Z"))).toBe(0);
      expect(nearestFrameIndexByTime(frames, new Date("2026-08-21T00:00:00Z"))).toBe(2);
    });

    it("空配列なら0を返す", () => {
      expect(nearestFrameIndexByTime([], new Date())).toBe(0);
    });
  });

  it("nowcastTileUrlTemplateはbasetime/validtimeを埋め込み{z}/{x}/{y}はプレースホルダのまま残す", () => {
    const url = nowcastTileUrlTemplate({ basetime: "20260820030000", validtime: "20260820030500", isForecast: true });
    expect(url).toBe(
      "https://www.jma.go.jp/bosai/jmatile/data/nowc/20260820030000/none/20260820030500/surf/hrpns/{z}/{x}/{y}.png",
    );
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

  describe("precipitationGridToFeatureCollection", () => {
    const grid: WindGridPoint[] = [
      {
        latitude: 35.68,
        longitude: 139.77,
        times: ["t0", "t1"],
        wind_speed_ms: [1, 2],
        wind_direction_deg: [10, 20],
        precipitation_mm: [0.5, 3.2],
      },
      {
        latitude: 36.0,
        longitude: 140.0,
        times: ["t0", "t1"],
        wind_speed_ms: [1, 2],
        wind_direction_deg: [10, 20],
        precipitation_mm: [0, 12.5],
      },
    ];

    it("指定フレームの降水量でGeoJSON FeatureCollectionを構築する", () => {
      const fc = precipitationGridToFeatureCollection(grid, 1);
      expect(fc.features).toHaveLength(2);
      expect(fc.features[0].geometry.coordinates).toEqual([139.77, 35.68]);
      expect(fc.features[0].properties.mmPerHour).toBe(3.2);
      expect(fc.features[1].properties.mmPerHour).toBe(12.5);
    });

    it("frameIndexが範囲外の格子点はスキップする(欠損に頑健)", () => {
      const fc = precipitationGridToFeatureCollection(grid, 5);
      expect(fc.features).toHaveLength(0);
    });

    it("空配列を渡すと空のFeatureCollectionを返す", () => {
      const fc = precipitationGridToFeatureCollection([], 0);
      expect(fc.features).toHaveLength(0);
    });
  });

  describe("buildCombinedPrecipitationFrames（ユーザー要望「1時間まで細かい目盛り、1時間から先は1時間毎の粗い目盛り」）", () => {
    function nowcastFrame(validtime: string, isForecast: boolean) {
      return { basetime: "a", validtime, isForecast };
    }

    it("ナウキャスト(実況/予測)を先頭へ、延長予報を後ろへ並べ、それぞれ正しいbadge・source・timeを付ける", () => {
      // 20260820030000 UTC = 12:00 JST。ナウキャストは実況1件・予測1件（12:00, 12:05 JST）。
      const nowcastFrames = [nowcastFrame("20260820030000", false), nowcastFrame("20260820030500", true)];
      // 延長側（風と共通の格子点マップ由来）は13:00, 14:00 JST（JSTのオフセット無し表記）。
      const extendedTimes = ["2026-08-20T13:00", "2026-08-20T14:00"];

      const frames = buildCombinedPrecipitationFrames(nowcastFrames, extendedTimes);

      expect(frames).toEqual([
        { time: parseValidtime("20260820030000"), label: "12:00", badge: "実況", source: "nowcast", sourceIndex: 0 },
        { time: parseValidtime("20260820030500"), label: "12:05", badge: "予測", source: "nowcast", sourceIndex: 1 },
        { time: parseJstTime("2026-08-20T13:00"), label: "8/20 13:00", badge: "広域予報", source: "extended", sourceIndex: 0 },
        { time: parseJstTime("2026-08-20T14:00"), label: "8/20 14:00", badge: "広域予報", source: "extended", sourceIndex: 1 },
      ]);
    });

    it("ナウキャストの最終フレーム以前の延長予報時刻は除外する(近い将来の二重表示を避ける)", () => {
      // ナウキャストの最終フレームは12:05 JST。延長側の12:00は最終フレームより前なので除外、
      // 13:00は最終フレームより後なので採用される。
      const nowcastFrames = [nowcastFrame("20260820030000", false), nowcastFrame("20260820030500", true)];
      const extendedTimes = ["2026-08-20T12:00", "2026-08-20T13:00"];

      const frames = buildCombinedPrecipitationFrames(nowcastFrames, extendedTimes);

      expect(frames.filter((f) => f.source === "extended")).toEqual([
        { time: parseJstTime("2026-08-20T13:00"), label: "8/20 13:00", badge: "広域予報", source: "extended", sourceIndex: 1 },
      ]);
    });

    it("ナウキャストが空でも延長予報だけの時系列を返す", () => {
      const frames = buildCombinedPrecipitationFrames([], ["2026-08-20T13:00"]);
      expect(frames).toEqual([
        { time: parseJstTime("2026-08-20T13:00"), label: "8/20 13:00", badge: "広域予報", source: "extended", sourceIndex: 0 },
      ]);
    });

    it("両方空なら空配列を返す", () => {
      expect(buildCombinedPrecipitationFrames([], [])).toEqual([]);
    });
  });

  describe("nearestCombinedPrecipitationFrameIndex", () => {
    const frames = buildCombinedPrecipitationFrames(
      [
        { basetime: "a", validtime: "20260820030000", isForecast: false },
        { basetime: "a", validtime: "20260820030500", isForecast: true },
      ],
      ["2026-08-20T13:00", "2026-08-20T14:00"]
    );

    it("対象時刻に最も近いフレームのindexを返す", () => {
      // 12:03 JSTは12:00(index0)より12:05(index1)に近い。
      expect(nearestCombinedPrecipitationFrameIndex(frames, new Date("2026-08-20T12:03:00+09:00"))).toBe(1);
      // 13:40 JSTは13:00(index2)より14:00(index3)に近い。
      expect(nearestCombinedPrecipitationFrameIndex(frames, new Date("2026-08-20T13:40:00+09:00"))).toBe(3);
    });

    it("空配列なら0を返す", () => {
      expect(nearestCombinedPrecipitationFrameIndex([], new Date())).toBe(0);
    });
  });
});
