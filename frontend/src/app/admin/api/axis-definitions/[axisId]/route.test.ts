// @vitest-environment node
// 軸CRUD管理APIのroute handler（改善計画T331）。PUT/DELETEがNext.js 16のPromise化された
// paramsからaxisIdを取り出し、encodeURIComponentしたうえでproxyToBackendAdminへ委譲することを
// 確認する（proxyToBackendAdmin自体の挙動はlib/adminApiProxy.test.tsで検証済み）。
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/adminApiProxy", () => ({
  proxyToBackendAdmin: vi.fn(),
}));

import { proxyToBackendAdmin } from "@/lib/adminApiProxy";
import { DELETE, PUT } from "./route";

describe("PUT/DELETE /admin/api/axis-definitions/[axisId]", () => {
  it("PUTはaxisIdをpathへ埋め込みproxyToBackendAdminへ委譲する", async () => {
    const sentinelResponse = new Response(null, { status: 200 });
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(sentinelResponse);

    const request = new Request("https://example.test/admin/api/axis-definitions/surface_q", {
      method: "PUT",
      body: JSON.stringify({ label: "路面品質" }),
    });
    const response = await PUT(request, { params: Promise.resolve({ axisId: "surface_q" }) });

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(request, "/api/admin/axis-definitions/surface_q");
    expect(response).toBe(sentinelResponse);
  });

  it("DELETEはaxisIdをpathへ埋め込みproxyToBackendAdminへ委譲する", async () => {
    const sentinelResponse = new Response(null, { status: 204 });
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(sentinelResponse);

    const request = new Request("https://example.test/admin/api/axis-definitions/surface_q", { method: "DELETE" });
    const response = await DELETE(request, { params: Promise.resolve({ axisId: "surface_q" }) });

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(request, "/api/admin/axis-definitions/surface_q");
    expect(response).toBe(sentinelResponse);
  });

  it("axisIdはencodeURIComponentしてからpathへ埋め込む（記号・日本語混じりのIDでも安全に）", async () => {
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(new Response(null, { status: 200 }));

    const request = new Request("https://example.test/admin/api/axis-definitions/x", { method: "PUT" });
    await PUT(request, { params: Promise.resolve({ axisId: "路面/品質 軸" }) });

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(
      request,
      `/api/admin/axis-definitions/${encodeURIComponent("路面/品質 軸")}`,
    );
  });
});
