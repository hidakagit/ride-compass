// @vitest-environment node
/**
 * `debugAdminApi.ts`——ログの絞り込みを、backendが受ける問い合わせの項目として渡すこと。
 *
 * 項目名の期待値はbackendの契約（`openapi.json`）から取る。
 *
 * ここで見ないもの:
 * - 叩く口・待ち時間 → `adminApiClients.test.ts`
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getRecentLogs } from "./debugAdminApi";

interface Parameter {
  name: string;
  in: string;
}
const openApi = JSON.parse(readFileSync(join(__dirname, "../../types/generated/openapi.json"), "utf-8"));
const acceptedQuery = new Set(
  (openApi.paths["/api/admin/debug/logs"].get.parameters as Parameter[])
    .filter((parameter) => parameter.in === "query")
    .map((parameter) => parameter.name),
);

let requestedUrl = "";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      requestedUrl = url;
      return new Response(JSON.stringify(["line 1", "line 2"]), { status: 200 });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getRecentLogs", () => {
  it("件数・部分一致・最低レベルを、backendが受ける問い合わせの項目で渡し、ログ行をそのまま返す", async () => {
    await expect(getRecentLogs({ limit: 200, contains: "jma tile", minLevel: "WARNING" })).resolves.toEqual([
      "line 1",
      "line 2",
    ]);

    const query = new URL(requestedUrl, "http://frontend.test").searchParams;
    const keys = [...query.keys()];
    expect(keys).toHaveLength(3);
    for (const key of keys) expect(acceptedQuery).toContain(key);
    expect([...query.values()].sort()).toEqual(["200", "WARNING", "jma tile"]);
  });

  it("絞り込みを指定しなければ、問い合わせを付けない（backendの既定＝保持している全件）", async () => {
    await getRecentLogs();
    expect(requestedUrl).not.toContain("?");
  });

  it("部分一致が空文字なら、その項目を付けない", async () => {
    await getRecentLogs({ contains: "" });
    expect(requestedUrl).not.toContain("?");
  });
});
