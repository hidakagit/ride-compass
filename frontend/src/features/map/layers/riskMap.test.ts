// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeResponse } from "@/testing/fetchMocks";

import { jmaDelivery } from "./jmaNowcastFrames";
import { fetchCurrentRiskFrames, fetchLinearRainbandFrames } from "./riskMap";

const LAND = jmaDelivery("disaster/landslide");
const FLOOD = jmaDelivery("disaster/flood").id;
const RAINBAND = jmaDelivery("precipitationNowcast/linearRainband");
const SHORT_RANGE = jmaDelivery("precipitationNowcast/main", 1).id;
const fileOf = (delivery: { pathGroup: string; targetTimeFiles: readonly string[] }) =>
  `/api/jma-tile/bosai/jmatile/data/${delivery.pathGroup}/${delivery.targetTimeFiles[0]}`;

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFiles(files: Record<string, unknown[]>) {
  const fetchMock = vi.fn(async (url: string) =>
    url in files ? makeResponse({ json: async () => files[url] }) : makeResponse({ ok: false, status: 500 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const entry = (basetime: string, elements: string[], member = "none") => ({
  basetime,
  validtime: basetime,
  member,
  elements,
});

describe("fetchCurrentRiskFrames（キキクルの「現在」）", () => {
  it("要素ごとに、その要素を載せた最新の1件だけを「現在」のコマにする（無い要素は空）", async () => {
    const fetchMock = stubFiles({
      [fileOf(LAND)]: [
        entry("20260924000000", [LAND.id, FLOOD]),
        entry("20260924001000", [LAND.id]),
        entry("20260923235000", [FLOOD]),
      ],
    });
    const frames = await fetchCurrentRiskFrames();
    expect(frames.land).toEqual([
      {
        time: new Date("2026-09-24T00:10:00Z"),
        ref: expect.objectContaining({ basetime: "20260924001000", member: "none" }),
      },
    ]);
    expect(frames.flood.map((frame) => frame.ref.basetime)).toEqual(["20260924000000"]);
    expect(frames.heavyRain).toEqual([]);
    expect(frames.inundation).toEqual([]);
    // 同じファイルに載る要素どうしは往復を1回に畳む
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("時刻一覧が取れなければ投げる", async () => {
    stubFiles({});
    await expect(fetchCurrentRiskFrames()).rejects.toThrow("危険度分布（キキクル）");
  });
});

describe("fetchLinearRainbandFrames（線状降水帯予測の「現在」）", () => {
  it("降水短時間予報と同じファイルのうち、線状降水帯の行だけから最新の1件を取る", async () => {
    stubFiles({
      [fileOf(RAINBAND)]: [
        entry("20260924002000", [SHORT_RANGE], "immed"),
        entry("20260924001000", [RAINBAND.id], "immed"),
      ],
    });
    expect((await fetchLinearRainbandFrames()).map((frame) => frame.ref)).toEqual([
      expect.objectContaining({ basetime: "20260924001000", member: "immed" }),
    ]);
  });
});
