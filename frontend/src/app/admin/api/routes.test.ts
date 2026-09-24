// @vitest-environment node
/**
 * `app/admin/api/**\/route.ts`——管理画面の同一オリジンの口が、受けた要求をbackendの
 * 管理APIのどれへ渡すか。
 *
 * 母集団はこのディレクトリの`route.ts`と、それぞれがexportするHTTPメソッドで、期待値は
 * backendの契約（生成物`openapi.json`）から取る。どの口がどのパスへ渡すかを表として
 * 書き写さない——口が1つ増えても、この検査はそのまま効く。
 *
 * ここで見ないもの:
 * - 転送そのもの（資格情報の付与・クエリと本文の受け渡し・失敗時の502） → `lib/adminApiProxy.ts`
 * - ブラウザ側のクライアントがどの口を叩くか・待ち時間が口と揃っているか → `features/admin/adminApiClients.test.ts`
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/adminBasicAuth", () => ({
  adminBasicAuthCredentials: () => ({ username: "admin", password: "secret" }),
}));

const API_DIR = __dirname;
const HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"] as const;

interface OpenApi {
  paths: Record<string, Record<string, unknown>>;
}

const openApi: OpenApi = JSON.parse(readFileSync(join(__dirname, "../../../types/generated/openapi.json"), "utf-8"));

function routeFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return routeFiles(full);
    return name === "route.ts" ? [full] : [];
  });
}

/** `axis-definitions/[axisId]` → 動的な区間の名前（`axisId`）の並び。 */
function dynamicSegments(file: string): string[] {
  return relative(API_DIR, file)
    .split(sep)
    .flatMap((segment) => /^\[(.+)\]$/.exec(segment)?.[1] ?? []);
}

/** backendのパスが当たる契約のテンプレートと、`{...}`に入った値（復号済み）。 */
function matchBackendPath(pathname: string, method: string): { template: string; values: string[] }[] {
  return Object.entries(openApi.paths).flatMap(([template, operations]) => {
    if (!(method.toLowerCase() in operations)) return [];
    const pattern = new RegExp(`^${template.replace(/\{[^}]+\}/g, "([^/]+)")}$`);
    const match = pattern.exec(pathname);
    return match ? [{ template, values: match.slice(1).map(decodeURIComponent) }] : [];
  });
}

const files = routeFiles(API_DIR);

const backendRequests: { url: string; method: string }[] = [];

beforeEach(() => {
  backendRequests.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      backendRequests.push({ url, method: init.method ?? "GET" });
      return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("管理APIの口", () => {
  it("口が1つ以上ある", () => {
    expect(files.length).toBeGreaterThan(0);
  });

  it.each(files.map((file) => [relative(API_DIR, file).split(sep).join("/"), file]))(
    "%s: exportした各メソッドを、backendの契約にある同じメソッドのパスへ渡し、区間の値は1区間のまま届く",
    async (_name, file) => {
      const handlers: Record<string, unknown> = await import(/* @vite-ignore */ file);
      const methods = HTTP_METHODS.filter((method) => typeof handlers[method] === "function");
      expect(methods.length).toBeGreaterThan(0);

      // 区切り文字を含む値でも、backendのパスの1区間として届くこと（符号化を忘れると区間が増える）。
      const names = dynamicSegments(file);
      const params = Object.fromEntries(names.map((name) => [name, `${name}/値 1`]));

      for (const method of methods) {
        backendRequests.length = 0;
        const handler = handlers[method] as (request: Request, context: unknown) => Promise<Response>;
        const request = new Request("http://frontend.test/admin/api/x", {
          method,
          ...(method === "POST" || method === "PUT" ? { body: "{}" } : {}),
        });
        const response = await handler(request, { params: Promise.resolve(params) });

        expect(response.status).toBe(200);
        expect(backendRequests).toHaveLength(1);
        const [forwarded] = backendRequests;
        expect(forwarded.method).toBe(method);
        const matches = matchBackendPath(new URL(forwarded.url).pathname, method);
        expect(matches, `${method} ${forwarded.url} がbackendの契約に無い`).toHaveLength(1);
        expect(matches[0].values).toEqual(names.map((name) => params[name]));
      }
    },
  );
});
