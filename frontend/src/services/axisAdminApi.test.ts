// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AxisDefinitionPayload, AxisDefinitionResponse } from "@/types/route";
import {
  createAxisDefinition,
  deleteAxisDefinition,
  listAxisDefinitions,
  unpublishAxisDefinition,
  updateAxisDefinition,
} from "./axisAdminApi";

// 軸CRUD管理APIクライアント（lib/fetchJson.tsのGET専用パターンとは別にadminFetchを自前実装、
// axisAdminApi.tsのコメント参照）。AxisStudio.test.tsxはこのモジュール自体をモックしており
// adminFetchの実装コードが一度も実行されていなかった（改善計画T331）ため、
// lib/fetchJson.test.tsと同じ粒度でfetch呼び出しの組み立て・エラーハンドリングを検証する。

function makeResponse(overrides: Partial<{ ok: boolean; status: number; json: () => Promise<unknown>; headers: Headers }>) {
  return {
    ok: true,
    status: 200,
    json: async () => ({}),
    headers: new Headers(),
    ...overrides,
  };
}

const axisResponse: AxisDefinitionResponse = {
  axis_id: "surface_q",
  shape: { kind: "categorical", material: "surface_q", mapping: { paved: 1, unpaved: 0 } },
  default_weight: 1,
  label: "路面品質",
  description: "",
  category: "推定",
  is_published: false,
  show_map_icon: true,
  time_scope: "always",
  supports_route_coloring: false,
  // 改善計画T404: displayはAxisDefinitionResponseの必須フィールド（axis_display_for()の
  // 計算結果）。本テストは実際のderive_ramp_inputsの挙動を検証する対象ではないため
  // kind="none"の適当な値を置く。
  display: { kind: "none", label: "路面品質", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
};

const axisPayload: AxisDefinitionPayload = { ...axisResponse };

describe("axisAdminApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe("listAxisDefinitions", () => {
    it("GET /admin/api/axis-definitionsを呼び、JSONをそのまま返す", async () => {
      const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => [axisResponse] }));
      vi.stubGlobal("fetch", fetchMock);

      await expect(listAxisDefinitions()).resolves.toEqual([axisResponse]);

      const [path, init] = fetchMock.mock.calls[0];
      expect(path).toBe("/admin/api/axis-definitions");
      expect(init.method).toBe("GET");
      expect(init.body).toBeUndefined();
      expect(init.signal).toBeInstanceOf(AbortSignal);
    });
  });

  describe("createAxisDefinition", () => {
    it("POSTでJSON化したbodyとContent-Typeヘッダを送る", async () => {
      const fetchMock = vi.fn().mockResolvedValue(makeResponse({ status: 201, json: async () => axisResponse }));
      vi.stubGlobal("fetch", fetchMock);

      await expect(createAxisDefinition(axisPayload)).resolves.toEqual(axisResponse);

      const [path, init] = fetchMock.mock.calls[0];
      expect(path).toBe("/admin/api/axis-definitions");
      expect(init.method).toBe("POST");
      expect(init.headers).toEqual({ "Content-Type": "application/json" });
      expect(JSON.parse(init.body)).toEqual(axisPayload);
    });
  });

  describe("updateAxisDefinition", () => {
    it("PUTでaxisIdをencodeURIComponentしたパスへ送る", async () => {
      const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => axisResponse }));
      vi.stubGlobal("fetch", fetchMock);

      await updateAxisDefinition("axis/with space", axisPayload);

      const [path, init] = fetchMock.mock.calls[0];
      expect(path).toBe(`/admin/api/axis-definitions/${encodeURIComponent("axis/with space")}`);
      expect(init.method).toBe("PUT");
      expect(JSON.parse(init.body)).toEqual(axisPayload);
    });
  });

  describe("deleteAxisDefinition", () => {
    it("DELETEを送り、204レスポンスはundefinedを返す（json()を呼ばない）", async () => {
      const jsonSpy = vi.fn();
      const fetchMock = vi
        .fn()
        .mockResolvedValue(makeResponse({ status: 204, json: jsonSpy }));
      vi.stubGlobal("fetch", fetchMock);

      await expect(deleteAxisDefinition("surface_q")).resolves.toBeUndefined();

      const [path, init] = fetchMock.mock.calls[0];
      expect(path).toBe("/admin/api/axis-definitions/surface_q");
      expect(init.method).toBe("DELETE");
      expect(jsonSpy).not.toHaveBeenCalled();
    });
  });

  describe("unpublishAxisDefinition", () => {
    it("POST .../{axisId}/unpublish へbody無しで送る", async () => {
      const fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: async () => ({ ...axisResponse, is_published: false }) }));
      vi.stubGlobal("fetch", fetchMock);

      await unpublishAxisDefinition("surface_q");

      const [path, init] = fetchMock.mock.calls[0];
      expect(path).toBe("/admin/api/axis-definitions/surface_q/unpublish");
      expect(init.method).toBe("POST");
      expect(init.body).toBeUndefined();
    });
  });

  describe("エラーハンドリング", () => {
    it("ok:falseかつdetailが文字列の場合はそのdetailとx-request-idからエラーメッセージを組み立てる", async () => {
      const headers = new Headers({ "x-request-id": "req-123" });
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(makeResponse({ ok: false, status: 409, json: async () => ({ detail: "公開済みの軸は更新できません" }), headers })),
      );

      await expect(listAxisDefinitions()).rejects.toThrow("公開済みの軸は更新できません[req: req-123]");
    });

    it("ok:falseかつdetailが無い場合はフォールバックメッセージになる", async () => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeResponse({ ok: false, status: 500 })));

      await expect(listAxisDefinitions()).rejects.toThrow("リクエストに失敗しました[HTTP 500]");
    });

    it("errorBodyのjson()自体が失敗してもフォールバックメッセージで失敗する", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          makeResponse({
            ok: false,
            status: 500,
            json: async () => {
              throw new Error("parse failed");
            },
          }),
        ),
      );

      await expect(listAxisDefinitions()).rejects.toThrow("リクエストに失敗しました[HTTP 500]");
    });

    it("成功レスポンスのjson()解析が失敗した場合は解析失敗のエラーを投げる", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          makeResponse({
            json: async () => {
              throw new Error("parse failed");
            },
          }),
        ),
      );

      await expect(listAxisDefinitions()).rejects.toThrow("サーバーからの応答の解析に失敗しました");
    });

    it("fetch()自体が失敗した場合（通信エラー）は元の例外をそのまま投げる", async () => {
      vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

      await expect(listAxisDefinitions()).rejects.toThrow("Failed to fetch");
    });
  });
});
