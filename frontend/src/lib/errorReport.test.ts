/**
 * `lib/errorReport.ts`——画面で起きたエラーをbackendへ報告する口。報告は定期の見張りが読んで知らせるので、送り漏れは
 * 知らせが来ないこと、送りすぎは知らせが鳴り続けることになる。
 *
 * 送る出口（`navigator.sendBeacon`）はテスト環境に無いので代役へ差し替え、送った本文を読む。送ったことを覚える状態は
 * モジュールが持つので、テストごとにモジュールを読み込み直す（ページの再読み込みにあたる）。
 *
 * ここで見ないもの:
 * - backendが受ける形（名前・パスの綴り） → backendの`tests/test_error_reports_route.py`
 * - 画面が動き出す前に例外の出来事へ結ぶこと（`instrumentation-client.ts`） → Next.jsのファイルの決まり
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { API_BASE_URL } from "@/lib/apiBaseUrl";

let sendBeacon: ReturnType<typeof vi.fn<(url: string, body: Blob) => boolean>>;

beforeEach(() => {
  vi.resetModules();
  sendBeacon = vi.fn<(url: string, body: Blob) => boolean>(() => true);
  Object.defineProperty(navigator, "sendBeacon", { value: sendBeacon, configurable: true });
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  Reflect.deleteProperty(navigator, "sendBeacon");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function sentReports() {
  return Promise.all(
    sendBeacon.mock.calls.map(async ([url, body]) => ({ url, type: body.type, body: JSON.parse(await body.text()) })),
  );
}

describe("reportError", () => {
  it("種類・名前・画面のパスだけを、CORSの事前の問い合わせが起きない形で送る", async () => {
    const { reportError } = await import("@/lib/errorReport");
    window.history.replaceState(null, "", "/admin/axes?lat=35.68#x");

    reportError("exception", "TypeError");

    expect(await sentReports()).toEqual([
      {
        url: `${API_BASE_URL}/api/client-errors`,
        type: "text/plain",
        body: { kind: "exception", name: "TypeError", page: "/admin/axes" },
      },
    ]);
  });

  it("backendが受けない綴りの名前とパスは伏せて送る", async () => {
    const { reportError } = await import("@/lib/errorReport");
    window.history.replaceState(null, "", "/%E9%A7%85");

    reportError("network", "観測");

    expect((await sentReports()).map(({ body }) => body)).toEqual([{ kind: "network", name: "-", page: "/" }]);
  });

  it("同じ報告は1回の表示で1度だけ送り、送る件数に上限がある", async () => {
    const { MAX_REPORTS_PER_PAGE, reportError } = await import("@/lib/errorReport");

    reportError("render", "TypeError");
    reportError("render", "TypeError");
    for (let index = 0; index < MAX_REPORTS_PER_PAGE + 1; index += 1) reportError("exception", `Error${index}`);

    const names = (await sentReports()).map(({ body }) => body.name);
    expect(names).toHaveLength(MAX_REPORTS_PER_PAGE);
    expect(names.filter((name) => name === "TypeError")).toHaveLength(1);
  });

  it("読み込み直した画面では、同じ報告をまた送る", async () => {
    (await import("@/lib/errorReport")).reportError("render", "TypeError");
    vi.resetModules();
    (await import("@/lib/errorReport")).reportError("render", "TypeError");

    expect(sendBeacon).toHaveBeenCalledTimes(2);
  });
});

describe("backendへの通信の失敗", () => {
  const OPTIONS = { timeoutMs: 1000, category: "api:a", errorLabel: "資料A" };

  async function failFetch() {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );
    const { fetchJson } = await import("@/lib/apiClient");
    await fetchJson("https://example.test/feed.json", OPTIONS).catch(() => {});
  }

  it("骨格を通る呼び出しの通信の失敗を、呼び出しの分類の名前で送る", async () => {
    await failFetch();

    expect((await sentReports()).map(({ body }) => body)).toEqual([{ kind: "network", name: "api:a", page: "/" }]);
  });

  it("端末が網から外れている間の失敗は送らない", async () => {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);

    await failFetch();

    expect(sendBeacon).not.toHaveBeenCalled();
  });

  it("画面が裏に回っている間の失敗は送らない", async () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");

    await failFetch();

    expect(sendBeacon).not.toHaveBeenCalled();
  });
});
