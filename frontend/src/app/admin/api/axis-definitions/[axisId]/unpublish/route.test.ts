// @vitest-environment node
// 軸の公開解除API（改善計画T271「軸の公開フロー」・T331でroute handlerの未テストを解消）。
// POSTがNext.js 16のPromise化されたparamsからaxisIdを取り出し、encodeURIComponentしたうえで
// "/api/admin/axis-definitions/{axisId}/unpublish"へproxyToBackendAdminを委譲することを確認する。
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/adminApiProxy", () => ({
  proxyToBackendAdmin: vi.fn(),
}));

import { proxyToBackendAdmin } from "@/lib/adminApiProxy";
import { POST } from "./route";

describe("POST /admin/api/axis-definitions/[axisId]/unpublish", () => {
  it("axisIdをpathへ埋め込みunpublishエンドポイントへ委譲する", async () => {
    const sentinelResponse = new Response(null, { status: 200 });
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(sentinelResponse);

    const request = new Request("https://example.test/admin/api/axis-definitions/surface_q/unpublish", {
      method: "POST",
    });
    const response = await POST(request, { params: Promise.resolve({ axisId: "surface_q" }) });

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(request, "/api/admin/axis-definitions/surface_q/unpublish");
    expect(response).toBe(sentinelResponse);
  });

  it("axisIdはencodeURIComponentしてからpathへ埋め込む", async () => {
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(new Response(null, { status: 200 }));

    const request = new Request("https://example.test/admin/api/axis-definitions/x/unpublish", { method: "POST" });
    await POST(request, { params: Promise.resolve({ axisId: "路面/品質 軸" }) });

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(
      request,
      `/api/admin/axis-definitions/${encodeURIComponent("路面/品質 軸")}/unpublish`,
    );
  });
});
