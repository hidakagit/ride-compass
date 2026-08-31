// @vitest-environment node
// バックエンドログ表示パネル（改善計画T517）のroute handler。proxyToBackendAdmin自体の挙動
// （Basic認証ヘッダ組み立て・クエリ文字列転送・エラーハンドリング）はlib/adminApiProxy.test.ts
// で検証済みのため、ここではGETがproxyToBackendAdminへ正しいbackendPath
// （"/api/admin/debug/logs"）で委譲していることだけを確認する。
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/adminApiProxy", () => ({
  proxyToBackendAdmin: vi.fn(),
}));

import { proxyToBackendAdmin } from "@/lib/adminApiProxy";
import { GET } from "./route";

describe("GET /admin/api/debug/logs", () => {
  it("proxyToBackendAdminへ/api/admin/debug/logsで委譲する", async () => {
    const sentinelResponse = new Response(null, { status: 200 });
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(sentinelResponse);

    const request = new Request("https://example.test/admin/api/debug/logs?limit=200&contains=jma-tile", {
      method: "GET",
    });
    const response = await GET(request);

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(request, "/api/admin/debug/logs");
    expect(response).toBe(sentinelResponse);
  });
});
