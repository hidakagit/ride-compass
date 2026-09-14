// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { checkBackendHealth } from "./healthApi";

/** 共通骨格（lib/fetchJson.ts）はstatusとheadersも読む。Responseの最小形を揃えて渡す。 */
function response(init: { ok: boolean; json?: () => Promise<unknown> }) {
  return {
    ok: init.ok,
    status: init.ok ? 200 : 500,
    headers: new Headers(),
    json: init.json ?? (async () => ({})),
    text: async () => "",
  };
}

describe("checkBackendHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetchがok:trueかつstatus:okを返す場合はtrueを返す", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ok: true, json: async () => ({ status: "ok" }) })));

    await expect(checkBackendHealth()).resolves.toBe(true);
  });

  it("fetchがok:trueだがstatusがok以外の場合はfalseを返す", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response({ ok: true, json: async () => ({ status: "something-else" }) })),
    );

    await expect(checkBackendHealth()).resolves.toBe(false);
  });

  it("fetchがok:falseの場合はfalseを返す", async () => {
    // 本文を読むかどうかは共通骨格（lib/fetchJson.ts）の担当——失敗の中身をログへ残すため
    // 読む。ここが見るのは「呼び出し側へ返る値」だけにする。
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ok: false })));

    await expect(checkBackendHealth()).resolves.toBe(false);
  });

  it("fetchがネットワークエラーでrejectしても例外を投げずfalseを返す", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network error")));

    await expect(checkBackendHealth()).resolves.toBe(false);
  });
});
