// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  centerFramesAroundLatestObserved,
  fetchNowcastFrames,
  formatNowcastFrameTime,
  latestObservedFrameIndex,
  nowcastTileUrlTemplate,
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

  describe("centerFramesAroundLatestObserved（実機フィードバック「時間バーの現況を中央初期表示して」）", () => {
    function frame(validtime: string, isForecast: boolean) {
      return { basetime: "a", validtime, isForecast };
    }

    it("実況が予測よりずっと多いとき、実況側を予測側と同じ件数まで切り詰め「現在」が中央に来るようにする", () => {
      // 実況5件・予測2件 -> 実況を直近2件だけへ切り詰め、5件（実況2+現在1+予測2）で中央=index2
      const frames = [
        frame("1", false),
        frame("2", false),
        frame("3", false),
        frame("4", false),
        frame("5", false),
        frame("6", true),
        frame("7", true),
      ];
      const result = centerFramesAroundLatestObserved(frames);
      expect(result.map((f) => f.validtime)).toEqual(["3", "4", "5", "6", "7"]);
      expect(latestObservedFrameIndex(result)).toBe(2);
      expect(result.length % 2).toBe(1); // 奇数件数なら必ず中央index が存在する
    });

    it("「現在」の前後が既に同数（対称）なら何も切り詰めない", () => {
      // 実況3件（「現在」含む）・予測2件、「現在」の前後は2件ずつで既に対称
      const frames = [frame("1", false), frame("2", false), frame("3", false), frame("4", true), frame("5", true)];
      const result = centerFramesAroundLatestObserved(frames);
      expect(result).toEqual(frames);
    });

    it("予測が実況より多い場合も対称に切り詰める", () => {
      // 実況2件（「現在」含む、前に1件）・予測4件 -> 予測を前と同じ1件へ切り詰め
      const frames = [
        frame("1", false),
        frame("2", false),
        frame("3", true),
        frame("4", true),
        frame("5", true),
        frame("6", true),
      ];
      const result = centerFramesAroundLatestObserved(frames);
      expect(result.map((f) => f.validtime)).toEqual(["1", "2", "3"]);
    });

    it("空配列を渡すと空配列を返す", () => {
      expect(centerFramesAroundLatestObserved([])).toEqual([]);
    });
  });

  it("nowcastTileUrlTemplateはbasetime/validtimeを埋め込み{z}/{x}/{y}はプレースホルダのまま残す", () => {
    const url = nowcastTileUrlTemplate({ basetime: "20260820030000", validtime: "20260820030500", isForecast: true });
    expect(url).toBe(
      "https://www.jma.go.jp/bosai/jmatile/data/nowc/20260820030000/none/20260820030500/surf/hrpns/{z}/{x}/{y}.png",
    );
  });
});
