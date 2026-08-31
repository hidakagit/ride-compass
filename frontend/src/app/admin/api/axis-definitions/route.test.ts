// @vitest-environment node
// 軸CRUD管理APIのroute handler（改善計画T331）。proxyToBackendAdmin自体の挙動（Basic認証
// ヘッダ組み立て・転送・エラーハンドリング）はlib/adminApiProxy.test.tsで検証済みのため、
// ここではroute handlerがGET/POSTそれぞれをproxyToBackendAdminへ正しいbackendPath
// （"/api/admin/axis-definitions"）で委譲していることだけを確認する。
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/adminApiProxy", () => ({
  proxyToBackendAdmin: vi.fn(),
}));

import { proxyToBackendAdmin } from "@/lib/adminApiProxy";
import { GET, POST } from "./route";

describe("GET/POST /admin/api/axis-definitions", () => {
  it("GETはproxyToBackendAdminへ/api/admin/axis-definitionsで委譲する", async () => {
    const sentinelResponse = new Response(null, { status: 200 });
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(sentinelResponse);

    const request = new Request("https://example.test/admin/api/axis-definitions", { method: "GET" });
    const response = await GET(request);

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(request, "/api/admin/axis-definitions");
    expect(response).toBe(sentinelResponse);
  });

  it("POSTはproxyToBackendAdminへ/api/admin/axis-definitionsで委譲する", async () => {
    const sentinelResponse = new Response(null, { status: 201 });
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(sentinelResponse);

    const request = new Request("https://example.test/admin/api/axis-definitions", {
      method: "POST",
      body: JSON.stringify({ axis_id: "surface_q" }),
    });
    const response = await POST(request);

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(request, "/api/admin/axis-definitions");
    expect(response).toBe(sentinelResponse);
  });
});
