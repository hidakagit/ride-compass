// @vitest-environment node
/**
 * `services/axisCatalogApi.ts`——軸カタログをbackendから取る口。入口は`getAxisCatalog`、差し替えるのは網（msw）で、
 * 確かめるのは戻り値。
 *
 * ここで見ないもの:
 * - 失敗を投げること・失敗の文言の組み立て・通信の失敗とタイムアウトの包み直し → `lib/apiClient.test.ts`
 * - 届いたカタログを画面の形へ移すこと・失敗したときの空のカタログ → `hooks/useAxisCatalog.test.ts`
 */
import { describe, expect, it } from "vitest";

import { onBackend } from "@/testing/backendServer";
import { catalogResponse } from "@/testing/catalogAxes";

import { getAxisCatalog } from "./axisCatalogApi";

describe("getAxisCatalog", () => {
  it("軸カタログを取り、届いた本文をそのまま返す", async () => {
    const catalog = catalogResponse([], { tile_versions: { road_surface: "r1" } });
    onBackend("GET", "/api/axis-catalog", () => Response.json(catalog));

    await expect(getAxisCatalog()).resolves.toEqual(catalog);
  });
});
