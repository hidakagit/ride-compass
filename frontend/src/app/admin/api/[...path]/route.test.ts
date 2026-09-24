// @vitest-environment node
/**
 * `app/admin/api/[...path]/route.ts`——`/admin/api/<X>`への要求を、資格情報を付けてbackendの`/api/admin/<X>`へ
 * そのまま渡し、応答をそのまま返すこと。
 *
 * 母集団はbackendの契約（生成物`openapi.json`）にある管理APIの操作の全部。
 *
 * ここで見ないもの:
 * - 管理画面のクライアントが叩く先・待ち時間 → `features/admin/adminApi.test.ts`
 * - 資格情報の「片方だけ設定」の扱い → `lib/adminBasicAuth.ts`
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BACKEND_INTERNAL_URL } from "@/lib/backendInternalUrl";

import * as route from "./route";

let credentials: { username: string; password: string } | null = null;
vi.mock("@/lib/adminBasicAuth", () => ({ adminBasicAuthCredentials: () => credentials }));

const handlers = route as unknown as Record<string, (request: Request) => Promise<Response>>;

const openApi: { paths: Record<string, Record<string, unknown>> } = JSON.parse(
  readFileSync(join(__dirname, "../../../../types/generated/openapi.json"), "utf-8"),
);
const operations = Object.entries(openApi.paths)
  .filter(([path]) => path.startsWith("/api/admin/"))
  .flatMap(([path, ops]) => Object.keys(ops).map((method) => [method.toUpperCase(), path] as const));

interface Forwarded {
  url: string;
  init: RequestInit;
}
let forwarded: Forwarded[] = [];
let backendResponse: () => Response;

beforeEach(() => {
  credentials = { username: "admin", password: "s3cret" };
  forwarded = [];
  backendResponse = () => new Response('{"ok":true}', { status: 200, headers: { "content-type": "application/json" } });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      forwarded.push({ url, init });
      return backendResponse();
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function call(method: string, path: string, body?: string) {
  return handlers[method](new Request(`http://frontend.test${path}`, { method, body }));
}

describe("管理APIの口", () => {
  it("契約に管理APIの操作が1つ以上ある", () => {
    expect(operations.length).toBeGreaterThan(0);
  });

  it.each(operations)("%s %s: 同じメソッド・同じパスへ、区間の値を1区間のまま渡す", async (method, template) => {
    // 区切り文字を含む値でも1区間のまま届くこと（復号し直すと区間が増える）。
    const path = template.replace(/\{[^}]+\}/g, encodeURIComponent("値/1"));
    const hasBody = method === "POST" || method === "PUT";
    const response = await call(
      method,
      path.replace(/^\/api\/admin/, "/admin/api") + "?limit=5",
      hasBody ? "{}" : undefined,
    );

    expect(response.status).toBe(200);
    expect(forwarded).toHaveLength(1);
    expect(forwarded[0].url).toBe(`${BACKEND_INTERNAL_URL}${path}?limit=5`);
    expect(forwarded[0].init.method).toBe(method);
  });

  it("Basic認証の資格情報を付ける", async () => {
    await call("GET", "/admin/api/db-status");
    expect(new Headers(forwarded[0].init.headers).get("Authorization")).toBe(
      `Basic ${Buffer.from("admin:s3cret").toString("base64")}`,
    );
  });

  it("POST・PUTは本文をJSONとしてそのまま渡し、GET・DELETEは本文を渡さない", async () => {
    await call("PUT", "/admin/api/tuning/a", '{"value":1}');
    await call("DELETE", "/admin/api/axis-definitions/a");
    expect(forwarded[0].init.body).toBe('{"value":1}');
    expect(new Headers(forwarded[0].init.headers).get("Content-Type")).toBe("application/json");
    expect(forwarded[1].init.body).toBeUndefined();
    expect(new Headers(forwarded[1].init.headers).has("Content-Type")).toBe(false);
  });

  it("backendの状態と本文をそのまま返す（誤りも、204も）", async () => {
    backendResponse = () => new Response('{"detail":"表示名が空です"}', { status: 422 });
    const failed = await call("POST", "/admin/api/axis-definitions", "{}");
    expect(failed.status).toBe(422);
    await expect(failed.json()).resolves.toEqual({ detail: "表示名が空です" });

    backendResponse = () => new Response(null, { status: 204 });
    expect((await call("DELETE", "/admin/api/axis-definitions/a")).status).toBe(204);
  });

  it("backendへ届かなければ502で、ランタイムの英語の文言は本文へ入れない", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    const response = await call("GET", "/admin/api/db-status");
    expect(response.status).toBe(502);
    const { detail } = await response.json();
    expect(detail).toContain("通信エラー");
    expect(detail).not.toContain("fetch failed");
  });

  it("`..`で`/admin/api`の外へ出るパスは、backendへ渡さない", async () => {
    const response = await call("GET", "/admin/api/../../api/debug/stats");
    expect(response.status).toBe(404);
    expect(forwarded).toHaveLength(0);
  });

  it("サーバーに資格情報が無ければ500で、backendへは渡さない", async () => {
    credentials = null;
    const response = await call("GET", "/admin/api/db-status");
    expect(response.status).toBe(500);
    expect(forwarded).toHaveLength(0);
  });
});
