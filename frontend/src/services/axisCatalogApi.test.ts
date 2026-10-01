// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AxisCatalogResponse } from "@/types/route";
import { getAxisCatalog } from "./axisCatalogApi";

describe("getAxisCatalog", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時はJSONをそのまま返す", async () => {
    const catalog: AxisCatalogResponse = {
      axes: [],
      tile_runtime_scales: {},
      client_tuning: {},
      accident_years: [],
      tile_versions: {},
    };
    const fetchMock = vi.fn<(request: Request) => Promise<Response>>(async () => Response.json(catalog));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getAxisCatalog()).resolves.toEqual(catalog);
    // 既定値NEXT_PUBLIC_API_URL未設定時はhttp://localhost:8000宛
    expect(fetchMock.mock.calls[0][0].url).toBe("http://localhost:8000/api/axis-catalog");
  });

  it("失敗は評価軸カタログの文言で投げる", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 500 })));
    await expect(getAxisCatalog()).rejects.toThrow("評価軸カタログの取得に失敗しました[HTTP 500]");
  });
});
