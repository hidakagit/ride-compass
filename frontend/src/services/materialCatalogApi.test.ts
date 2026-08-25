// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MaterialCatalogResponse } from "@/types/route";
import { getMaterialCatalog } from "./materialCatalogApi";

function makeResponse(overrides: Partial<{ ok: boolean; status: number; json: () => Promise<unknown>; headers: Headers }>) {
  return {
    ok: true,
    status: 200,
    json: async () => ({}),
    headers: new Headers(),
    ...overrides,
  };
}

describe("getMaterialCatalog", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時はJSONをそのまま返す", async () => {
    const catalog: MaterialCatalogResponse = { materials: [] };
    const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => catalog }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getMaterialCatalog()).resolves.toEqual(catalog);
    // 既定値NEXT_PUBLIC_API_URL未設定時はhttp://localhost:8000宛
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/material-catalog", expect.anything());
  });

  it("ok:falseの場合はHTTPステータスを含むエラーを投げる", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse({ ok: false, status: 500 })));

    await expect(getMaterialCatalog()).rejects.toThrow("材料カタログの取得に失敗しました[HTTP 500]");
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

    await expect(getMaterialCatalog()).rejects.toThrow("材料カタログの解析に失敗しました");
  });

  it("fetch自体が失敗した場合（通信エラー）もそのままエラーを投げる", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(getMaterialCatalog()).rejects.toThrow("Failed to fetch");
  });
});
