// @vitest-environment node
/**
 * `services/axisCatalogApi.ts`——軸カタログをbackendから取る口。入口は`getAxisCatalog`、差し替えるのは網（`fetch`）で、
 * 確かめるのは送った要求と戻り値。
 *
 * ここで見ないもの:
 * - 失敗の文言の組み立て・通信の失敗とタイムアウトの包み直し → `lib/apiClient.test.ts`
 * - 届いたカタログを画面の形へ移すこと・失敗したときの空のカタログ → `hooks/useAxisCatalog.test.ts`
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { stubBackend } from "@/testing/backendFetch";

import { getAxisCatalog } from "./axisCatalogApi";

describe("getAxisCatalog", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("軸カタログをGETで取り、届いた本文をそのまま返す", async () => {
    const catalog = { axes: [], tile_versions: { road_surface: "r1" }, tile_runtime_scales: {}, accident_years: [] };
    const sent = stubBackend(() => Response.json(catalog));

    await expect(getAxisCatalog()).resolves.toEqual(catalog);
    expect(sent).toEqual([{ method: "GET", path: "/api/axis-catalog", query: {}, body: undefined }]);
  });

  it("backendが失敗したら、空のカタログで返さずに投げる（呼ぶ側が「取得に失敗した」と知るため）", async () => {
    stubBackend(() => new Response(null, { status: 503 }));

    await expect(getAxisCatalog()).rejects.toThrow(Error);
  });
});
