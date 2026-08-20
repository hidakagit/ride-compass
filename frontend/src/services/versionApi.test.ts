// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FrontendVersion } from "./versionApi";
import { getFrontendVersion } from "./versionApi";

function makeResponse(overrides: Partial<{ ok: boolean; status: number; json: () => Promise<unknown>; headers: Headers }>) {
  return {
    ok: true,
    status: 200,
    json: async () => ({}),
    headers: new Headers(),
    ...overrides,
  };
}

describe("getFrontendVersion", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時はJSONをそのまま返す", async () => {
    const version: FrontendVersion = { commit: "abc1234", started_at: "2026-08-16T10:00:00+00:00" };
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => version }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getFrontendVersion()).resolves.toEqual(version);
    // バックエンドAPIではなく常に相対パスで同一オリジン（フロント自身）へ問い合わせる
    expect(fetchMock).toHaveBeenCalledWith("/api/version", expect.anything());
  });

  it("ok:falseの場合はHTTPステータスを含むエラーを投げる", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse({ ok: false, status: 500 })));

    await expect(getFrontendVersion()).rejects.toThrow("フロントエンドのバージョンの取得に失敗しました[HTTP 500]");
  });

  it("jsonのparseが失敗した場合は解析失敗のエラーを投げる", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse({
          json: async () => {
            throw new Error("parse failed");
          },
        }),
      ),
    );

    await expect(getFrontendVersion()).rejects.toThrow("フロントエンドのバージョンの解析に失敗しました");
  });

  it("fetch自体が失敗した場合（通信エラー）もそのままエラーを投げる", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(getFrontendVersion()).rejects.toThrow("Failed to fetch");
  });
});
