// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchNowcastFrames,
  formatNowcastFrameTime,
  latestObservedFrameIndex,
  nearestFrameIndexByTime,
  nowcastTileUrlTemplate,
  trimToCurrentAndFuture,
} from "./precipitationNowcast";

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
});
