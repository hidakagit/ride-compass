// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { debugLog } from "@/lib/debugLog";

// 失敗時のdebugLogの呼び出し回数・ラベルを直接アサートするためモックする。
vi.mock("@/lib/debugLog", () => ({ debugLog: vi.fn() }));

import { refreshTileCache } from "./basemapAdminApi";

describe("refreshTileCache", () => {
  afterEach(() => {
    vi.mocked(debugLog).mockClear();
  });

  it("POSTで同一オリジンの/admin/api/basemap-refreshへ呼ばれる", async () => {
    // backendの/api/admin/basemap/refreshはBasic認証必須のため、ブラウザからは直接
    // 叩かず、/adminのroute handler（同一オリジン）経由で認証情報を再利用する。
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => ({ status: "ok" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await refreshTileCache();

    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/admin/api/basemap-refresh");
    expect(String(url)).not.toContain("/api/admin/basemap/refresh");
    expect(options.method).toBe("POST");
  });

  it("fetchがok:falseの場合は例外を投げる（無反応に見えるサイレント失敗にしない）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        headers: new Headers(),
        json: async () => ({}),
      }),
    );

    await expect(refreshTileCache()).rejects.toThrow(/502/);
  });

  // 共有骨格（lib/fetchJson.ts）が、!response.ok時のthrowを同じtry節のcatchで再捕捉し
  // 「失敗 (HTTP xxx)」の直後に「失敗 (通信エラー)」を二重ログしないことの回帰テスト。
  it("HTTPエラー時はdebugLogが「失敗 (HTTP xxx)」で1回だけ呼ばれ、「通信エラー」では呼ばれない", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        headers: new Headers(),
        json: async () => ({}),
      }),
    );

    await expect(refreshTileCache()).rejects.toThrow(/502/);

    const calls = vi.mocked(debugLog).mock.calls.filter(([category]) => category === "api:basemap-refresh");
    expect(calls).toHaveLength(2); // 「リクエスト開始」＋「失敗 (HTTP 502)」
    expect(calls.map(([, message]) => message)).toEqual(["リクエスト開始", "失敗 (HTTP 502)"]);
    expect(calls.some(([, message]) => message === "失敗 (通信エラー)")).toBe(false);
  });

  it("fetch自体が例外を投げる場合もエラーとして伝播する", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network error")));

    await expect(refreshTileCache()).rejects.toThrow("network error");
  });
});
