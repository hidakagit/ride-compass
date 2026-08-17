// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { checkBackendHealth } from "./healthApi";

describe("checkBackendHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetchがok:trueかつstatus:okを返す場合はtrueを返す", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok" }),
      }),
    );

    await expect(checkBackendHealth()).resolves.toBe(true);
  });

  it("fetchがok:trueだがstatusがok以外の場合はfalseを返す", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "something-else" }),
      }),
    );

    await expect(checkBackendHealth()).resolves.toBe(false);
  });

  it("fetchがok:falseの場合はjsonを呼ばずにfalseを返す", async () => {
    const json = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        json,
      }),
    );

    await expect(checkBackendHealth()).resolves.toBe(false);
    expect(json).not.toHaveBeenCalled();
  });

  it("fetchがネットワークエラーでrejectしても例外を投げずfalseを返す", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network error")));

    await expect(checkBackendHealth()).resolves.toBe(false);
  });
});
