// @vitest-environment node
// 較正値1件の書き換えのroute handler。Next.js 16でPromise化されたparamsからparamIdを
// 取り出し、encodeURIComponentしたうえでbackendのパスへ委譲することを確認する
// （proxyToBackendAdmin自体の挙動はlib/adminApiProxy.test.tsで検証済み）。
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/adminApiProxy", () => ({
  proxyToBackendAdmin: vi.fn(),
}));

import { proxyToBackendAdmin } from "@/lib/adminApiProxy";
import { PUT } from "./route";

describe("PUT /admin/api/tuning/[paramId]", () => {
  it("paramIdをpathへ埋め込みproxyToBackendAdminへ委譲する", async () => {
    const sentinelResponse = new Response(null, { status: 200 });
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(sentinelResponse);

    const request = new Request("https://example.test/admin/api/tuning/turn.right_seconds", {
      method: "PUT",
      body: JSON.stringify({ value: 14 }),
    });
    const response = await PUT(request, { params: Promise.resolve({ paramId: "turn.right_seconds" }) });

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(request, "/api/admin/tuning/turn.right_seconds");
    expect(response).toBe(sentinelResponse);
  });

  it("idのドットはそのまま通す（較正値のidは必ずドットを含む）", async () => {
    // `encodeURIComponent`はドットを変換しない。ここで変換される実装へ変わると、
    // backendの`TUNING_PARAMETERS_BY_ID`が引けず全件404になる。
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(new Response(null, { status: 200 }));

    const request = new Request("https://example.test/admin/api/tuning/x", { method: "PUT" });
    await PUT(request, { params: Promise.resolve({ paramId: "splice.min_stretch_km" }) });

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(request, "/api/admin/tuning/splice.min_stretch_km");
  });

  it("paramIdはencodeURIComponentしてからpathへ埋め込む", async () => {
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(new Response(null, { status: 200 }));

    const request = new Request("https://example.test/admin/api/tuning/x", { method: "PUT" });
    await PUT(request, { params: Promise.resolve({ paramId: "turn/right 秒" }) });

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(
      request,
      `/api/admin/tuning/${encodeURIComponent("turn/right 秒")}`,
    );
  });
});
