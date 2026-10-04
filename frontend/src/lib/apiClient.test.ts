// @vitest-environment node
/**
 * `lib/apiClient.ts`——backendを呼ぶ全呼び出しが共有する骨格。成功した応答の本体を返し、失敗は利用者へ出せる
 * 日本語の文言の`Error`で投げ、経過をデバッグの記録へ残す。
 *
 * 網は`fetch`を差し替えて作る（応答・通信の失敗・時間切れ）。記録は本物の`lib/debugLog.ts`へ届いたものを読む
 * （記録はデバッグの画面に出る、この骨格の出力）。
 *
 * ここで見ないもの:
 * - `detail`の中身を文言にする規則（入力検証の失敗の配列等） → `lib/apiError.test.ts`
 * - 呼び出し口ごとの叩く先（backendのオリジン・管理APIの同一オリジンの口）と文言の主語 → 呼び出す側
 *   （`app/admin/adminApi.test.ts`・`services/*Api.test.ts`等）
 * - デバッグモードがオフのとき記録しないこと → `lib/debugLog.test.ts`
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { backendApi, fetchJson, requestApi } from "@/lib/apiClient";
import { clearDebugLog, getDebugLogEntries, setDebugEnabled } from "@/lib/debugLog";

const URL_A = "https://example.test/feed.json";
const OPTIONS = { timeoutMs: 1000, category: "api:a", errorLabel: "資料A" };

let fetchMock: ReturnType<typeof vi.fn<(request: Request) => Promise<Response>>>;

beforeEach(() => {
  setDebugEnabled(true);
  clearDebugLog();
  vi.spyOn(console, "debug").mockImplementation(() => {});
  vi.spyOn(console, "error").mockImplementation(() => {});
  fetchMock = vi.fn<(request: Request) => Promise<Response>>();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { "content-type": "application/json", ...init.headers },
  });
}

function logged() {
  return getDebugLogEntries().map(({ category, message, detail, level }) => ({ category, message, detail, level }));
}

function rejection(promise: Promise<unknown>): Promise<Error> {
  return promise.then(
    () => {
      throw new Error("成功してしまった");
    },
    (error: Error) => error,
  );
}

describe("成功", () => {
  it("応答の本体を返し、開始と成功を記録する（開始には呼び出し側の情報を、成功には要求のidを添える）", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ value: 1 }, { headers: { "x-request-id": "req-1" } }));

    const data = await fetchJson<{ value: number }>(URL_A, { ...OPTIONS, requestMeta: { region: "r1" } });

    expect(data).toEqual({ value: 1 });
    expect(logged()).toEqual([
      {
        category: "api:a",
        message: "リクエスト開始",
        detail: { method: "GET", url: URL_A, region: "r1" },
        level: "info",
      },
      {
        category: "api:a",
        message: "成功",
        detail: { url: URL_A, durationMs: expect.any(Number), requestId: "req-1" },
        level: "info",
      },
    ]);
  });

  it("成功の記録へ、応答から呼び出し側が数えた情報を足す", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ axes: [{}, {}, {}] }));

    await requestApi((init) => backendApi.GET("/api/axis-catalog", init), {
      timeoutMs: 1000,
      category: "api:a",
      messages: { failure: "失敗", parseFailure: "解析の失敗" },
      successMeta: (data) => ({ count: data.axes.length }),
    });

    expect(logged().at(-1)?.detail).toMatchObject({ count: 3 });
  });
});

describe("HTTPの失敗", () => {
  it("backendが`detail`を返せば、それを文言にし、状態と本文と要求のidを記録する", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "経路が見つかりません" }, { status: 404, headers: { "x-request-id": "req-1" } }),
    );

    const error = await rejection(fetchJson(URL_A, OPTIONS));

    expect(error.message).toBe("経路が見つかりません");
    expect(logged().at(-1)).toEqual({
      category: "api:a",
      message: "失敗 (HTTP 404)",
      detail: {
        url: URL_A,
        durationMs: expect.any(Number),
        requestId: "req-1",
        errorBody: { detail: "経路が見つかりません" },
      },
      level: "error",
    });
  });

  it.each([
    ["`detail`の無いJSON", () => jsonResponse({ message: "busy" }, { status: 503 })],
    ["JSONでない本文", () => new Response("Service Unavailable", { status: 503 })],
  ])("%sなら、呼び出し側の文言に状態を添える", async (_scene, response) => {
    fetchMock.mockResolvedValue(response());

    const error = await rejection(fetchJson(URL_A, OPTIONS));

    expect(error.message).toBe("資料Aの取得に失敗しました[HTTP 503]");
  });
});

describe("応答が届く前の失敗", () => {
  it("通信の失敗は、呼び出し側の文言に[通信エラー]を添え、ブラウザの英語の文言は原因と記録にだけ残す", async () => {
    const cause = new TypeError("Failed to fetch");
    fetchMock.mockRejectedValue(cause);

    const error = await rejection(fetchJson(URL_A, OPTIONS));

    expect(error.message).toBe("資料Aの取得に失敗しました[通信エラー]");
    expect(error.cause).toBe(cause);
    expect(logged().at(-1)).toEqual({
      category: "api:a",
      message: "失敗 (通信エラー)",
      detail: { url: URL_A, durationMs: expect.any(Number), error: "TypeError: Failed to fetch" },
      level: "error",
    });
  });

  it("ブラウザが失敗の手掛かり（`cause`）を付けていれば、それも記録する", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed", { cause: new Error("ECONNREFUSED") }));

    await rejection(fetchJson(URL_A, OPTIONS));

    expect(logged().at(-1)?.detail).toMatchObject({ cause: "Error: ECONNREFUSED" });
  });

  it("待ち時間を過ぎたら打ち切り、呼び出し側の文言に[タイムアウト]を添え、待ち時間を記録する", async () => {
    fetchMock.mockImplementation(
      (request) =>
        new Promise((_resolve, reject) => {
          request.signal.addEventListener("abort", () => reject(request.signal.reason));
        }),
    );

    const error = await rejection(fetchJson(URL_A, { ...OPTIONS, timeoutMs: 1 }));

    expect(error.message).toBe("資料Aの取得に失敗しました[タイムアウト]");
    expect(logged().at(-1)).toMatchObject({ message: "失敗 (タイムアウト 1ms)", level: "error" });
  });
});

describe("成功の応答の解析の失敗", () => {
  it("本文がJSONとして読めなければ、解析の失敗の文言で投げ、記録する", async () => {
    fetchMock.mockResolvedValue(new Response("<html>", { status: 200 }));

    const error = await rejection(fetchJson(URL_A, OPTIONS));

    expect(error.message).toBe("資料Aの解析に失敗しました");
    expect(error.cause).toBeInstanceOf(SyntaxError);
    expect(logged().at(-1)).toEqual({
      category: "api:a",
      message: "失敗 (不正なレスポンス)",
      detail: { url: URL_A, durationMs: expect.any(Number) },
      level: "error",
    });
  });
});
