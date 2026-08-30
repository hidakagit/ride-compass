// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchNowcastFrames,
  fetchRasrfFrames,
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

  describe("fetchRasrfFrames（改善計画T407: 降水短時間予報、immed=直近0〜6時間・none=7〜15時間先）", () => {
    const RASRF_ELEMENTS = ["rasrf", "rasrf_point", "rasrf_nd"];

    it("各memberの「複数フレームを持つ最新basetime」だけを採用し、validtime昇順で統合する", async () => {
      const raw = [
        // none: 10分毎の中間ラン（単発、validtime===basetime）は無視する。
        { basetime: "20260829161000", validtime: "20260829161000", member: "none", elements: RASRF_ELEMENTS },
        // none: 毎正時の完全な予報ラン（複数フレーム）。最新basetime=20260829160000を採用。
        { basetime: "20260829160000", validtime: "20260829230000", member: "none", elements: RASRF_ELEMENTS },
        { basetime: "20260829160000", validtime: "20260830000000", member: "none", elements: RASRF_ELEMENTS },
        // none: より古い完全な予報ラン（採用しない）。
        { basetime: "20260829150000", validtime: "20260829220000", member: "none", elements: RASRF_ELEMENTS },
        { basetime: "20260829150000", validtime: "20260829230000", member: "none", elements: RASRF_ELEMENTS },
        // immed: 最新basetime=20260829161000の完全な予報ラン。
        { basetime: "20260829161000", validtime: "20260829171000", member: "immed", elements: RASRF_ELEMENTS },
        { basetime: "20260829161000", validtime: "20260829181000", member: "immed", elements: RASRF_ELEMENTS },
      ];
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(raw))));

      const frames = await fetchRasrfFrames();

      expect(frames.map((f) => f.validtime)).toEqual(["20260829171000", "20260829181000", "20260829230000", "20260830000000"]);
      expect(frames.map((f) => f.member)).toEqual(["immed", "immed", "none", "none"]);
      expect(frames.every((f) => f.isForecast)).toBe(true);
    });

    it("いずれかのmemberに完全な予報ランが無ければ、そのmember分は空のまま返す", async () => {
      const raw = [{ basetime: "20260829161000", validtime: "20260829161000", member: "none", elements: RASRF_ELEMENTS }];
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(raw))));

      expect(await fetchRasrfFrames()).toEqual([]);
    });

    it("elementsにrasrfを含まない行（線状降水帯予測マップ[sjfcstmap]等の別プロダクト）は除外する", async () => {
      // 実機確認（2026-08-30）で判明したパターン: 同じ(basetime, validtime, member)組に対し、
      // rasrfを含む行とsjfcstmap単体の行が別々に存在することがある。sjfcstmap単体行が
      // 複数validtimeの「完全な予報ラン」に誤ってカウントされ、rasrf画像が存在しない
      // タイルURLを組み立ててしまうことの回帰テスト。
      const raw = [
        // 完全な予報ラン（rasrf搭載、2 validtime）。
        { basetime: "20260829160000", validtime: "20260829230000", member: "none", elements: RASRF_ELEMENTS },
        { basetime: "20260829160000", validtime: "20260830000000", member: "none", elements: RASRF_ELEMENTS },
        // より新しいbasetimeだが、sjfcstmap単体（rasrf無し）の行しか無い中間ラン。
        // rasrfを含まないため「完全な予報ラン」として誤採用してはいけない。
        { basetime: "20260829163000", validtime: "20260829163000", member: "none", elements: ["sjfcstmap"] },
      ];
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(raw))));

      const frames = await fetchRasrfFrames();

      expect(frames.map((f) => f.validtime)).toEqual(["20260829230000", "20260830000000"]);
      expect(frames.every((f) => f.member === "none")).toBe(true);
    });

    it("応答が配列でなければ例外を投げる", async () => {
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse({ not: "an array" }))));

      await expect(fetchRasrfFrames()).rejects.toThrow();
    });
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

    it("改善計画T425回帰テスト: 実況フレームが1件も無い（全てisForecast=true）場合、末尾の1件だけに削られず全フレームを残す", () => {
      // 以前はフォールバックが逆転しており（latestObservedFrameIndexが末尾indexを返す）、
      // 実況0件時に最も未来の1フレームだけが残り、降水/雷/竜巻ナウキャストが実質空に
      // なっていた（ゼロベース網羅レビュー指摘）。
      const frames = [frame("1", true), frame("2", true), frame("3", true)];
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

  describe("precipitationFrames（T183+T407: ナウキャスト+降水短時間予報+延長予報のデータ取得層での統合、dynamicWeather.tsの共通フレーム列へ変換）", () => {
    function nowcastFrame(validtime: string, isForecast: boolean) {
      return { basetime: "a", validtime, isForecast };
    }
    function rasrfFrame(validtime: string) {
      return { basetime: "a", validtime, isForecast: true, member: "immed" };
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

    it("ナウキャスト→降水短時間予報→延長予報の順に並べ、それぞれ正しいref・timeを付ける", () => {
      // 20260820030000 UTC = 12:00 JST。ナウキャストは実況1件・予測1件（12:00, 12:05 JST）。
      const nowcastFrames = [nowcastFrame("20260820030000", false), nowcastFrame("20260820030500", true)];
      const rasrfFrames = [rasrfFrame("20260820040000"), rasrfFrame("20260820050000")]; // 13:00, 14:00 JST
      // 延長側（風と共通の格子点マップ由来）は15:00, 16:00 JST（JSTのオフセット無し表記）。
      const frames = precipitationFrames(nowcastFrames, rasrfFrames, extendedGrid(["2026-08-20T15:00", "2026-08-20T16:00"]));

      expect(frames).toEqual([
        { time: parseValidtime("20260820030000"), ref: { source: "nowcast", index: 0 } },
        { time: parseValidtime("20260820030500"), ref: { source: "nowcast", index: 1 } },
        { time: parseValidtime("20260820040000"), ref: { source: "rasrf", index: 0 } },
        { time: parseValidtime("20260820050000"), ref: { source: "rasrf", index: 1 } },
        { time: parseJstTime("2026-08-20T15:00"), ref: { source: "extended", index: 0 } },
        { time: parseJstTime("2026-08-20T16:00"), ref: { source: "extended", index: 1 } },
      ]);
    });

    it("ナウキャストの最終フレーム以前の降水短時間予報時刻は除外する(近い将来の二重表示を避ける)", () => {
      const nowcastFrames = [nowcastFrame("20260820030000", false), nowcastFrame("20260820030500", true)];
      const rasrfFrames = [rasrfFrame("20260820030000"), rasrfFrame("20260820040000")]; // 12:00(除外), 13:00(採用)
      const frames = precipitationFrames(nowcastFrames, rasrfFrames, []);

      expect(frames.filter((f) => f.ref.source === "rasrf")).toEqual([
        { time: parseValidtime("20260820040000"), ref: { source: "rasrf", index: 1 } },
      ]);
    });

    it("降水短時間予報の最終フレーム以前の延長予報時刻は除外する(rasrf→extended境界の二重表示を避ける)", () => {
      const rasrfFrames = [rasrfFrame("20260820040000")]; // 13:00 JST
      // 延長側の13:00はrasrfの最終フレームと同時刻なので除外、14:00は採用される。
      const frames = precipitationFrames([], rasrfFrames, extendedGrid(["2026-08-20T13:00", "2026-08-20T14:00"]));

      expect(frames.filter((f) => f.ref.source === "extended")).toEqual([
        { time: parseJstTime("2026-08-20T14:00"), ref: { source: "extended", index: 1 } },
      ]);
    });

    it("降水短時間予報が空でも、延長予報はナウキャストの最終フレーム基準でフォールバックする", () => {
      const nowcastFrames = [nowcastFrame("20260820030000", false), nowcastFrame("20260820030500", true)];
      const frames = precipitationFrames(nowcastFrames, [], extendedGrid(["2026-08-20T12:00", "2026-08-20T13:00"]));

      expect(frames.filter((f) => f.ref.source === "extended")).toEqual([
        { time: parseJstTime("2026-08-20T13:00"), ref: { source: "extended", index: 1 } },
      ]);
    });

    it("全て空なら空配列を返す", () => {
      expect(precipitationFrames([], [], [])).toEqual([]);
    });
  });

  describe("precipitationRenderPayload（アイコンは1つ、内部は時間によって使い分ける。sourceでrasterTile/gridFillを切り替える）", () => {
    const nowcastFrames = [{ basetime: "20260820030000", validtime: "20260820030500", isForecast: true }];
    const rasrfFrames = [
      { basetime: "20260820030000", validtime: "20260820040000", isForecast: true, member: "immed" },
    ];
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
      const payload = precipitationRenderPayload(nowcastFrames, rasrfFrames, extendedGrid, WIND_GRID_SPACING_DEG, {
        source: "nowcast",
        index: 0,
      });
      expect(payload).toEqual({
        kind: "rasterTile",
        tileUrlTemplate: "/api/jma-tile/bosai/jmatile/data/nowc/20260820030000/none/20260820030500/surf/hrpns/{z}/{x}/{y}.png",
      });
    });

    it("source=nowcastでも該当indexのフレームが無ければundefinedを返す", () => {
      expect(
        precipitationRenderPayload(nowcastFrames, rasrfFrames, extendedGrid, WIND_GRID_SPACING_DEG, {
          source: "nowcast",
          index: 5,
        })
      ).toBeUndefined();
    });

    it("source=rasrfならkind=rasterTileで、basetime/member/validtimeを埋め込んだタイルURLを返す", () => {
      const payload = precipitationRenderPayload(nowcastFrames, rasrfFrames, extendedGrid, WIND_GRID_SPACING_DEG, {
        source: "rasrf",
        index: 0,
      });
      expect(payload).toEqual({
        kind: "rasterTile",
        tileUrlTemplate: "/api/jma-tile/bosai/jmatile/data/rasrf/20260820030000/immed/20260820040000/surf/rasrf/{z}/{x}/{y}.png",
      });
    });

    it("source=rasrfでも該当indexのフレームが無ければundefinedを返す", () => {
      expect(
        precipitationRenderPayload(nowcastFrames, rasrfFrames, extendedGrid, WIND_GRID_SPACING_DEG, {
          source: "rasrf",
          index: 5,
        })
      ).toBeUndefined();
    });

    it("source=extendedならkind=gridFillで、指定indexの降水量からGeoJSON Polygonを構築する", () => {
      const payload = precipitationRenderPayload(nowcastFrames, rasrfFrames, extendedGrid, WIND_GRID_SPACING_DEG, {
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
      expect(
        precipitationRenderPayload(nowcastFrames, rasrfFrames, [], WIND_GRID_SPACING_DEG, { source: "extended", index: 0 })
      ).toBeUndefined();
    });

    it("source=extendedで値が欠損している格子点はスキップする(欠損に頑健)", () => {
      const payload = precipitationRenderPayload(nowcastFrames, rasrfFrames, extendedGrid, WIND_GRID_SPACING_DEG, {
        source: "extended",
        index: 5,
      });
      expect(payload?.kind).toBe("gridFill");
      if (payload?.kind !== "gridFill") throw new Error("unreachable");
      expect(payload.geojson.features).toHaveLength(0);
    });
  });
});
