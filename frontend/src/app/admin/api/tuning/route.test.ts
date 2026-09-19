// @vitest-environment node
// 較正値の一覧のroute handler。backendのパスへそのまま委譲することだけを確認する
// （proxyToBackendAdmin自体の挙動はlib/adminApiProxy.test.tsで検証済み）。
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/adminApiProxy", () => ({
  proxyToBackendAdmin: vi.fn(),
}));

import { proxyToBackendAdmin } from "@/lib/adminApiProxy";
import { GET } from "./route";

describe("GET /admin/api/tuning", () => {
  it("backendの一覧へ委譲し、応答をそのまま返す", async () => {
    const sentinelResponse = new Response(null, { status: 200 });
    vi.mocked(proxyToBackendAdmin).mockResolvedValue(sentinelResponse);

    const request = new Request("https://example.test/admin/api/tuning");
    const response = await GET(request);

    expect(proxyToBackendAdmin).toHaveBeenCalledWith(request, "/api/admin/tuning");
    expect(response).toBe(sentinelResponse);
  });
});
