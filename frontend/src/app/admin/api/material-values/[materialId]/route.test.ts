// @vitest-environment node
// 材料の値一覧APIのroute handler。Next.js 16のPromise化されたparamsからmaterialIdを
// 取り出し、encodeURIComponentしたうえでproxyToBackendAdminへ委譲することを確認する
// （proxyToBackendAdmin自体の挙動はlib/adminApiProxy.test.tsで検証済み）。
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/adminApiProxy", () => ({
  proxyToBackendAdmin: vi.fn(),
}));

import { proxyToBackendAdmin } from "@/lib/adminApiProxy";
import { GET } from "./route";

describe("GET /admin/api/material-values/[materialId]", () => {
  it("materialIdをpathへ埋め込みproxyToBackendAdminへ委譲する", async () => {
    const sentinelResponse = new Response(null, { status: 200 });
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(sentinelResponse);

    const request = new Request("https://example.test/admin/api/material-values/highway");
    const response = await GET(request, { params: Promise.resolve({ materialId: "highway" }) });

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(request, "/api/admin/material-catalog/highway/values");
    expect(response).toBe(sentinelResponse);
  });

  it("materialIdをURLエンコードする", async () => {
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(new Response(null, { status: 200 }));

    const request = new Request("https://example.test/admin/api/material-values/a%2Fb");
    await GET(request, { params: Promise.resolve({ materialId: "a/b" }) });

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(request, "/api/admin/material-catalog/a%2Fb/values");
  });
});
