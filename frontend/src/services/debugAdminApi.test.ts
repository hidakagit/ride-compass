// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { getRecentLogs } from "./debugAdminApi";

// backendの直近ログ取得API（GET /api/admin/debug/logs、改善計画T379・T517）のクライアント。
// lib/fetchJson.test.tsと同じ粒度で、クエリ文字列の組み立て・エラーハンドリングを検証する。

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(response: { ok: boolean; status?: number; json: () => Promise<unknown> }) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("getRecentLogs", () => {
  it("パラメータ無しではクエリ文字列を付けずに叩く", async () => {
    const fetchMock = stubFetch({ ok: true, json: async () => ["line1"] });

    const result = await getRecentLogs();

    expect(result).toEqual(["line1"]);
    expect(fetchMock).toHaveBeenCalledWith("/admin/api/debug/logs", expect.anything());
  });

  it("limit/contains/minLevelをクエリ文字列へ組み立てる", async () => {
    const fetchMock = stubFetch({ ok: true, json: async () => [] });

    await getRecentLogs({ limit: 200, contains: "jma-tile", minLevel: "WARNING" });

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/admin/api/debug/logs?limit=200&contains=jma-tile&min_level=WARNING");
  });

  it("backendがエラーを返すとdetailを含む例外を投げる", async () => {
    stubFetch({ ok: false, status: 422, json: async () => ({ detail: "min_levelの値が不正です" }) });

    await expect(getRecentLogs({})).rejects.toThrow("min_levelの値が不正です");
  });

  it("fetch自体が失敗すると通信エラーとして例外を投げる", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("fetch failed")),
    );

    await expect(getRecentLogs({})).rejects.toThrow("ログの取得に失敗しました");
  });
});
