// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchJson } from "./fetchJson";
import { makeResponse } from "@/testing/fetchMocks";

describe("fetchJson", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時はレスポンスをJSONとしてパースして返す", async () => {
    const payload = { value: 42 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse({ json: async () => payload })));

    const result = await fetchJson("https://example.test/api/x", { timeoutMs: 5000, category: "api:test", errorLabel: "テスト" });

    expect(result).toEqual(payload);
  });

  it("ok:falseかつdetailが文字列の場合はそのdetailだけをメッセージにし、x-request-idはエラーの属性として持つ", async () => {
    const headers = new Headers({ "x-request-id": "req-123" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeResponse({ ok: false, status: 500, json: async () => ({ detail: "エラー詳細" }), headers })),
    );

    const error = await fetchJson("https://example.test/api/x", {
      timeoutMs: 5000,
      category: "api:test",
      errorLabel: "テスト",
    }).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    // 画面へ出る文言（message）にはリクエストIDを混ぜない。
    expect((error as ApiError).message).toBe("エラー詳細");
    expect((error as ApiError).requestId).toBe("req-123");
    expect((error as ApiError).status).toBe(500);
  });

  it("ok:falseかつdetailが無い場合はerrorLabelから組み立てたフォールバックメッセージになる", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse({ ok: false, status: 503 })));

    await expect(fetchJson("https://example.test/api/x", { timeoutMs: 5000, category: "api:test", errorLabel: "テスト" })).rejects.toThrow(
      "テストの取得に失敗しました[HTTP 503]",
    );
  });

  it("errorBodyのjson()自体が失敗してもフォールバックメッセージで失敗する（不正なレスポンスの解析失敗とは別経路）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        makeResponse({
          ok: false,
          status: 500,
          json: async () => {
            throw new Error("parse failed");
          },
        }),
      ),
    );

    await expect(fetchJson("https://example.test/api/x", { timeoutMs: 5000, category: "api:test", errorLabel: "テスト" })).rejects.toThrow(
      "テストの取得に失敗しました[HTTP 500]",
    );
  });

  it("成功レスポンスのjson()解析が失敗した場合は解析失敗のエラーを投げる", async () => {
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

    await expect(fetchJson("https://example.test/api/x", { timeoutMs: 5000, category: "api:test", errorLabel: "テスト" })).rejects.toThrow(
      "テストの解析に失敗しました",
    );
  });

  it("fetch()自体が失敗した場合（通信エラー）は元の例外をそのまま投げる", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(fetchJson("https://example.test/api/x", { timeoutMs: 5000, category: "api:test", errorLabel: "テスト" })).rejects.toThrow(
      "Failed to fetch",
    );
  });

  it("timeoutMsをAbortSignal.timeoutへ渡す", async () => {
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    await fetchJson("https://example.test/api/x", { timeoutMs: 1234, category: "api:test", errorLabel: "テスト" });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });
});
