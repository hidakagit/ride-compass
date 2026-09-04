// @vitest-environment node
// 材料の欠損割合パネル（MaterialCoveragePanel）のroute handler。proxyToBackendAdmin自体の
// 挙動はlib/adminApiProxy.test.tsで検証済みのため、ここではGETが正しいbackendPathと
// 延長タイムアウトで委譲していることだけを確認する。
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/adminApiProxy", () => ({
  proxyToBackendAdmin: vi.fn(),
}));

import { proxyToBackendAdmin } from "@/lib/adminApiProxy";
import { COVERAGE_PROXY_TIMEOUT_MS, GET } from "./route";

describe("GET /admin/api/material-coverage", () => {
  it("proxyToBackendAdminへ/api/admin/material-catalog/coverageと延長タイムアウトで委譲する", async () => {
    const sentinelResponse = new Response(null, { status: 200 });
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(sentinelResponse);

    const request = new Request("https://example.test/admin/api/material-coverage", { method: "GET" });
    const response = await GET(request);

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(request, "/api/admin/material-catalog/coverage", {
      timeoutMs: COVERAGE_PROXY_TIMEOUT_MS,
    });
    expect(COVERAGE_PROXY_TIMEOUT_MS).toBeGreaterThan(15000);
    expect(response).toBe(sentinelResponse);
  });
});
