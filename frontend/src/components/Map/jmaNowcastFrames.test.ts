// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchJmaTargetTimes } from "./jmaNowcastFrames";

// trimToCurrentAndFuture/parseValidtimeの挙動自体はprecipitationNowcast.test.ts（同じ実装の
// 再エクスポート）で検証済みのため、ここではjmaNowcastFrames.ts固有の追加分
// （fetchJmaTargetTimesのラベル付きエラーメッセージ）だけを検証する（改善計画T204）。
function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body, headers: new Headers() };
}

describe("fetchJmaTargetTimes", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時はJSON配列をそのまま返す", async () => {
    const raw = [{ basetime: "1", validtime: "1" }];
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse(raw)))
    );

    const result = await fetchJmaTargetTimes("https://example.test/targetTimes.json", "雷ナウキャスト");
    expect(result).toEqual(raw);
  });

  it("HTTPエラー時はlabelを含むエラーメッセージで例外を投げる", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse(null, false, 503)))
    );

    await expect(fetchJmaTargetTimes("https://example.test/targetTimes.json", "雷ナウキャスト")).rejects.toThrow(
      "雷ナウキャストの時刻一覧の取得に失敗しました[HTTP 503]"
    );
  });

  it("レスポンスが配列でない場合はlabelを含むエラーメッセージで例外を投げる", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse({ not: "an array" })))
    );

    await expect(fetchJmaTargetTimes("https://example.test/targetTimes.json", "雷ナウキャスト")).rejects.toThrow(
      "雷ナウキャストの時刻一覧の形式が想定と異なります"
    );
  });
});
