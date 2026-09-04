// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { proxyToBackendAdmin } from "./adminApiProxy";

// backendのadmin API群（軸CRUD・ログ取得等）へのサーバー側プロキシ（改善計画T305、
// T517で汎用化）。AxisStudio.test.tsxがaxisAdminApi.tsモジュール全体をモックするため、
// その先で実際にbackendへ転送するこのモジュールの実装コードは一度も実行されていなかった
// （改善計画T331）。lib/fetchJson.test.tsと同じ粒度でBasic認証ヘッダの組み立て・転送・
// エラーハンドリングを検証する。

const ORIGINAL_ENV = { ...process.env };

function resetEnv() {
  delete process.env.ADMIN_BASIC_AUTH_USERNAME;
  delete process.env.ADMIN_BASIC_AUTH_PASSWORD;
}

function setCreds() {
  process.env.ADMIN_BASIC_AUTH_USERNAME = "admin";
  process.env.ADMIN_BASIC_AUTH_PASSWORD = "s3cret";
}

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  vi.unstubAllGlobals();
});

describe("proxyToBackendAdmin", () => {
  describe("サーバー側資格情報が未設定", () => {
    beforeEach(() => resetEnv());

    it("500を返しbackendへfetchしない", async () => {
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);

      const response = await proxyToBackendAdmin(new Request("https://example.test/admin/api/axis-definitions"), "/api/admin/axis-definitions");

      expect(response.status).toBe(500);
      const body = await response.json();
      expect(body.detail).toContain("ADMIN_BASIC_AUTH_USERNAME/PASSWORD");
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it("USERNAMEのみ設定（PASSWORD未設定）でも500を返す", async () => {
      process.env.ADMIN_BASIC_AUTH_USERNAME = "admin";
      const response = await proxyToBackendAdmin(new Request("https://example.test/admin/api/axis-definitions"), "/api/admin/axis-definitions");
      expect(response.status).toBe(500);
    });
  });

  describe("資格情報設定済み", () => {
    beforeEach(() => {
      resetEnv();
      setCreds();
    });

    it("GETをbackendへ転送し、Basic認証ヘッダを付与、bodyは送らない", async () => {
      const backendResponse = new Response(JSON.stringify([{ axis_id: "surface_q" }]), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
      const fetchMock = vi.fn().mockResolvedValue(backendResponse);
      vi.stubGlobal("fetch", fetchMock);

      const response = await proxyToBackendAdmin(
        new Request("https://example.test/admin/api/axis-definitions", { method: "GET" }),
        "/api/admin/axis-definitions",
      );

      expect(response.status).toBe(200);
      await expect(response.json()).resolves.toEqual([{ axis_id: "surface_q" }]);

      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe("http://localhost:8000/api/admin/axis-definitions");
      expect(init.method).toBe("GET");
      expect(init.headers.Authorization).toBe(`Basic ${Buffer.from("admin:s3cret").toString("base64")}`);
      expect(init.headers["Content-Type"]).toBeUndefined();
      expect(init.body).toBeUndefined();
    });

    it("T517: リクエストのクエリ文字列をbackendPathへそのまま付け足して転送する", async () => {
      const backendResponse = new Response(JSON.stringify(["line1", "line2"]), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
      const fetchMock = vi.fn().mockResolvedValue(backendResponse);
      vi.stubGlobal("fetch", fetchMock);

      await proxyToBackendAdmin(
        new Request("https://example.test/admin/api/debug/logs?limit=200&contains=jma-tile", { method: "GET" }),
        "/api/admin/debug/logs",
      );

      const [url] = fetchMock.mock.calls[0];
      expect(url).toBe("http://localhost:8000/api/admin/debug/logs?limit=200&contains=jma-tile");
    });

    it("timeoutMs省略時は15秒、指定時はその値でAbortSignal.timeoutを組み立てる", async () => {
      const fetchMock = vi
        .fn()
        .mockImplementation(async () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
      vi.stubGlobal("fetch", fetchMock);
      const timeoutSpy = vi.spyOn(AbortSignal, "timeout");

      await proxyToBackendAdmin(new Request("https://example.test/admin/api/axis-definitions"), "/api/admin/axis-definitions");
      await proxyToBackendAdmin(
        new Request("https://example.test/admin/api/material-coverage"),
        "/api/admin/material-catalog/coverage",
        { timeoutMs: 90000 },
      );

      expect(timeoutSpy).toHaveBeenNthCalledWith(1, 15000);
      expect(timeoutSpy).toHaveBeenNthCalledWith(2, 90000);
      timeoutSpy.mockRestore();
    });

    it("POSTはリクエストボディをそのまま転送しContent-Typeを付与する", async () => {
      const backendResponse = new Response(JSON.stringify({ axis_id: "surface_q" }), {
        status: 201,
        headers: { "content-type": "application/json" },
      });
      const fetchMock = vi.fn().mockResolvedValue(backendResponse);
      vi.stubGlobal("fetch", fetchMock);

      const payload = { axis_id: "surface_q", default_weight: 1 };
      const response = await proxyToBackendAdmin(
        new Request("https://example.test/admin/api/axis-definitions", {
          method: "POST",
          body: JSON.stringify(payload),
        }),
        "/api/admin/axis-definitions",
      );

      expect(response.status).toBe(201);
      const [, init] = fetchMock.mock.calls[0];
      expect(init.method).toBe("POST");
      expect(init.headers["Content-Type"]).toBe("application/json");
      expect(JSON.parse(init.body)).toEqual(payload);
    });

    it("PUTもリクエストボディを転送する", async () => {
      const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
      vi.stubGlobal("fetch", fetchMock);

      await proxyToBackendAdmin(
        new Request("https://example.test/admin/api/axis-definitions/surface_q", {
          method: "PUT",
          body: JSON.stringify({ label: "路面品質" }),
        }),
        "/api/admin/axis-definitions/surface_q",
      );

      const [, init] = fetchMock.mock.calls[0];
      expect(init.method).toBe("PUT");
      expect(JSON.parse(init.body)).toEqual({ label: "路面品質" });
    });

    it("DELETEはbodyを送らずContent-Typeも付与しない", async () => {
      const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
      vi.stubGlobal("fetch", fetchMock);

      const response = await proxyToBackendAdmin(
        new Request("https://example.test/admin/api/axis-definitions/surface_q", { method: "DELETE" }),
        "/api/admin/axis-definitions/surface_q",
      );

      expect(response.status).toBe(204);
      const [, init] = fetchMock.mock.calls[0];
      expect(init.method).toBe("DELETE");
      expect(init.body).toBeUndefined();
      expect(init.headers["Content-Type"]).toBeUndefined();
    });

    it("backendが204を返した場合はレスポンスボディを読まずにそのまま204を返す", async () => {
      const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
      vi.stubGlobal("fetch", fetchMock);

      const response = await proxyToBackendAdmin(
        new Request("https://example.test/admin/api/axis-definitions/surface_q", { method: "DELETE" }),
        "/api/admin/axis-definitions/surface_q",
      );

      expect(response.status).toBe(204);
      expect(response.body).toBeNull();
    });

    it("backendのcontent-typeヘッダが無い場合はapplication/jsonへフォールバックする", async () => {
      // Responseコンストラクタは文字列bodyへ既定でtext/plainを付けてしまうため、
      // 「backendがcontent-typeを一切返さない」状況はfetch戻り値を素のオブジェクトにして再現する。
      const fetchMock = vi.fn().mockResolvedValue({
        status: 200,
        headers: new Headers(),
        text: async () => "{}",
      });
      vi.stubGlobal("fetch", fetchMock);

      const response = await proxyToBackendAdmin(
        new Request("https://example.test/admin/api/axis-definitions", { method: "GET" }),
        "/api/admin/axis-definitions",
      );

      expect(response.headers.get("content-type")).toBe("application/json");
    });

    it("backendのHTTPエラーステータスをそのまま返す", async () => {
      const fetchMock = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "公開済みの軸は更新できません" }), {
          status: 409,
          headers: { "content-type": "application/json" },
        }),
      );
      vi.stubGlobal("fetch", fetchMock);

      const response = await proxyToBackendAdmin(
        new Request("https://example.test/admin/api/axis-definitions/surface_q", {
          method: "PUT",
          body: JSON.stringify({}),
        }),
        "/api/admin/axis-definitions/surface_q",
      );

      expect(response.status).toBe(409);
      await expect(response.json()).resolves.toEqual({ detail: "公開済みの軸は更新できません" });
    });

    it("fetch()自体が失敗した場合（通信エラー）は502とエラー詳細を返す", async () => {
      vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

      const response = await proxyToBackendAdmin(
        new Request("https://example.test/admin/api/axis-definitions", { method: "GET" }),
        "/api/admin/axis-definitions",
      );

      expect(response.status).toBe(502);
      const body = await response.json();
      expect(body.detail).toContain("backendへの接続に失敗しました");
      expect(body.detail).toContain("fetch failed");
    });
  });
});
