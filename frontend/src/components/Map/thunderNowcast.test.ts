// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchThunderNowcastFrames,
  thunderFrames,
  thunderRenderPayload,
  tornadoRenderPayload,
  THUNDER_ACTIVITY_LEVELS,
  TORNADO_POTENTIAL_LEVELS,
} from "./thunderNowcast";
import { trimToCurrentAndFuture } from "./jmaNowcastFrames";

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body, headers: new Headers() };
}

// 実機確認（2026-08-22）で得た実際のtargetTimes_N3.json構造を模したフィクスチャ:
// 古いbasetimeの行はvalidtime===basetime（実況のみ）、最新basetimeの行だけ
// validtime>basetimeの予測が複数並ぶ。
const N3 = [
  { basetime: "20260822055500", validtime: "20260822055500", elements: ["thns", "thns_nd", "trns", "trns_nd"] },
  { basetime: "20260822060000", validtime: "20260822060000", elements: ["thns", "thns_nd", "trns", "trns_nd"] },
  { basetime: "20260822085000", validtime: "20260822085000", elements: ["thns", "thns_nd", "trns", "trns_nd"] },
  { basetime: "20260822085000", validtime: "20260822090000", elements: ["thns", "thns_nd", "trns", "trns_nd"] },
  { basetime: "20260822085000", validtime: "20260822091000", elements: ["thns", "thns_nd", "trns", "trns_nd"] },
];

describe("thunderNowcast（改善計画T204）", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetchThunderNowcastFramesはtargetTimes_N3.json 1本からvalidtime昇順のフレーム列を返し、isForecastをvalidtime>basetimeで判定する", async () => {
    let requestedUrl = "";
    const fetchMock = vi.fn((url: string) => {
      requestedUrl = url;
      return Promise.resolve(jsonResponse(N3));
    });
    vi.stubGlobal("fetch", fetchMock);

    const frames = await fetchThunderNowcastFrames();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(requestedUrl).toContain("targetTimes_N3.json");
    expect(frames.map((f) => f.validtime)).toEqual([
      "20260822055500",
      "20260822060000",
      "20260822085000",
      "20260822090000",
      "20260822091000",
    ]);
    expect(frames.map((f) => f.isForecast)).toEqual([false, false, false, true, true]);
  });

  // 実機のtargetTimes_N3.jsonは5分おきにエントリを持つが、雷・竜巻(thns/trns)自体は
  // 10分おきにしか更新されない。5分ズレた奇数番目のエントリは"elements": ["liden"]
  // （雷放電位置データのみ）しか持たず、thns/trnsのタイルは存在しない（改善計画T514
  // フォローアップ、実機のbackendログでbasetime=16:25/16:35[いずれも5分ズレ]を使った
  // 雷ナウキャストタイルがhttp_404になることを確認済み）。
  const N3_WITH_LIDEN_ONLY_GAP = [
    { basetime: "20260831165000", validtime: "20260831165000", elements: ["thns", "thns_nd", "trns", "trns_nd"] },
    { basetime: "20260831165500", validtime: "20260831165500", elements: ["liden"] },
  ];

  it("targetTimes_N3.jsonの最新エントリがliden-only（thns/trnsを持たない5分ズレ）でも、直近のthns/trnsを持つエントリまで遡って『現在』フレームとして使う（改善計画T514フォローアップ）", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(N3_WITH_LIDEN_ONLY_GAP))));

    const frames = await fetchThunderNowcastFrames();
    const trimmed = trimToCurrentAndFuture(frames);

    // 最新のliden-onlyエントリ(16:55)ではなく、直前のthns/trns有りエントリ(16:50)が
    // 「現在」として使われるべき——そうでないと、雷ナウキャストのタイルURLが
    // thns/trnsを持たないbasetimeで組み立てられ、常に404になる。
    expect(trimmed[0].basetime).toBe("20260831165000");
    const payload = thunderRenderPayload(trimmed, 0);
    expect(payload).toEqual({
      kind: "rasterTile",
      tileUrlTemplate: "/api/jma-tile/bosai/jmatile/data/nowc/20260831165000/none/20260831165000/surf/thns/{z}/{x}/{y}.png",
    });
  });

  it("取得に失敗した場合は例外を投げる", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse(null, false, 500)))
    );
    await expect(fetchThunderNowcastFrames()).rejects.toThrow();
  });

  describe("thunderFrames", () => {
    it("フレーム列をdynamicWeather.tsの共通フレーム列（refはindex）へ変換する", () => {
      const frames = [
        { basetime: "20260822085000", validtime: "20260822085000", isForecast: false },
        { basetime: "20260822085000", validtime: "20260822090000", isForecast: true },
      ];
      const result = thunderFrames(frames);
      expect(result).toHaveLength(2);
      expect(result[0].ref).toBe(0);
      expect(result[1].ref).toBe(1);
      expect(result[0].time.toISOString()).toBe("2026-08-22T08:50:00.000Z");
    });
  });

  describe("thunderRenderPayload / tornadoRenderPayload", () => {
    const frames = [{ basetime: "20260822085000", validtime: "20260822090000", isForecast: true }];

    it("thunderRenderPayloadはプロダクトコードthnsのrasterTileペイロードを返す", () => {
      const payload = thunderRenderPayload(frames, 0);
      expect(payload).toEqual({
        kind: "rasterTile",
        tileUrlTemplate: "/api/jma-tile/bosai/jmatile/data/nowc/20260822085000/none/20260822090000/surf/thns/{z}/{x}/{y}.png",
      });
    });

    it("tornadoRenderPayloadはプロダクトコードtrnsのrasterTileペイロードを返す（同じフレーム・同じref）", () => {
      const payload = tornadoRenderPayload(frames, 0);
      expect(payload).toEqual({
        kind: "rasterTile",
        tileUrlTemplate: "/api/jma-tile/bosai/jmatile/data/nowc/20260822085000/none/20260822090000/surf/trns/{z}/{x}/{y}.png",
      });
    });

    it("範囲外のrefに対してはundefinedを返す（1点の欠損で表示全体を落とさない）", () => {
      expect(thunderRenderPayload(frames, 5)).toBeUndefined();
      expect(tornadoRenderPayload(frames, 5)).toBeUndefined();
    });
  });

  describe("凡例", () => {
    it("THUNDER_ACTIVITY_LEVELSは活動度1〜4の4段階を持つ", () => {
      expect(THUNDER_ACTIVITY_LEVELS).toHaveLength(4);
      expect(THUNDER_ACTIVITY_LEVELS.map((l) => l.key)).toEqual(["level1", "level2", "level3", "level4"]);
    });

    it("TORNADO_POTENTIAL_LEVELSは発生確度1・2の2段階を持つ", () => {
      expect(TORNADO_POTENTIAL_LEVELS).toHaveLength(2);
      expect(TORNADO_POTENTIAL_LEVELS.map((l) => l.key)).toEqual(["potential1", "potential2"]);
    });
  });
});
