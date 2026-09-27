// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { adminApiClient, backendApi, fetchJson } from "./apiClient";

const URL_ = "https://example.test/api/x";
const OPTIONS = { timeoutMs: 5000, category: "api:test", errorLabel: "テスト" };

/** fetchが`outcome`を返す（`Response`でなければ投げる）。 */
function answer(outcome: Response | Error | DOMException) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      if (!(outcome instanceof Response)) throw outcome;
      return outcome;
    }),
  );
}

describe("骨格（fetchJson）", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時はレスポンスをJSONとしてパースして返す", async () => {
    answer(Response.json({ value: 42 }));
    await expect(fetchJson(URL_, OPTIONS)).resolves.toEqual({ value: 42 });
  });

  it("本文の無い成功（204）はundefinedを返す", async () => {
    answer(new Response(null, { status: 204 }));
    await expect(fetchJson(URL_, OPTIONS)).resolves.toBeUndefined();
  });

  it("HTTPエラーでdetailが文字列ならそのdetailだけをメッセージにする（リクエストIDを混ぜない）", async () => {
    answer(Response.json({ detail: "エラー詳細" }, { status: 500, headers: { "x-request-id": "req-123" } }));
    const error = await fetchJson(URL_, OPTIONS).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("エラー詳細");
  });

  it("422の検証エラー（detailが配列）は各項目のmsgをつないだ文言にする", async () => {
    answer(Response.json({ detail: [{ msg: "範囲外です" }, { msg: "必須です" }] }, { status: 422 }));
    await expect(fetchJson(URL_, OPTIONS)).rejects.toThrow("範囲外です / 必須です");
  });

  it("HTTPエラーでdetailが無い・本文がJSONでないならerrorLabelから組み立てた文言になる", async () => {
    answer(new Response(null, { status: 503 }));
    await expect(fetchJson(URL_, OPTIONS)).rejects.toThrow("テストの取得に失敗しました[HTTP 503]");
    answer(new Response("<html>Bad Gateway</html>", { status: 502 }));
    await expect(fetchJson(URL_, OPTIONS)).rejects.toThrow("テストの取得に失敗しました[HTTP 502]");
  });

  it("成功応答の本文がJSONとして読めなければ解析失敗のエラーを投げる", async () => {
    answer(new Response("{not json", { status: 200 }));
    await expect(fetchJson(URL_, OPTIONS)).rejects.toThrow("テストの解析に失敗しました");
  });

  it("fetch()自体が失敗した場合（通信エラー）は、英語の元の文言をmessageへ入れずcauseに残す", async () => {
    const original = new TypeError("Failed to fetch");
    answer(original);
    const error = await fetchJson(URL_, OPTIONS).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("テストの取得に失敗しました[通信エラー]");
    expect((error as Error).cause).toBe(original);
  });

  it("タイムアウトは通信エラーと区別した文言で投げ、待ち時間は指定した値で打ち切る", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    answer(new DOMException("signal timed out", "TimeoutError"));
    await expect(fetchJson(URL_, { ...OPTIONS, timeoutMs: 1234 })).rejects.toThrow(
      "テストの取得に失敗しました[タイムアウト]",
    );
    expect(timeout).toHaveBeenCalledWith(1234);
    timeout.mockRestore();
  });
});

describe("呼び出し口の型はbackendの契約から決まる", () => {
  it("宣言に無いパス・問い合わせの項目の欠けは型検査で落ちる", () => {
    const neverCalled = () => {
      // @ts-expect-error backendの宣言に無いパス。
      void backendApi.GET("/api/no-such-endpoint");
      // @ts-expect-error 必須の問い合わせの項目（longitude）が欠けている。
      void backendApi.GET("/api/weather", { params: { query: { latitude: 35 } } });
      // @ts-expect-error 管理APIの口はbackendのパスの`/api/admin`より後で呼ぶ。
      void adminApiClient.GET("/api/admin/db-status");
    };
    expect(neverCalled).toBeTypeOf("function");
  });
});
