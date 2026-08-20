// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import {
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

  it("nowcastTileUrlTemplateはbasetime/validtimeを埋め込み{z}/{x}/{y}はプレースホルダのまま残す", () => {
    const url = nowcastTileUrlTemplate({ basetime: "20260820030000", validtime: "20260820030500", isForecast: true });
    expect(url).toBe(
      "https://www.jma.go.jp/bosai/jmatile/data/nowc/20260820030000/none/20260820030500/surf/hrpns/{z}/{x}/{y}.png",
    );
  });
});
