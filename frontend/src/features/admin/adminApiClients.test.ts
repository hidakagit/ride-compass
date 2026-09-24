// @vitest-environment node
/**
 * `features/admin/*Api.ts`——管理画面のAPIクライアントが叩く先に、受け手がいること。
 *
 * 母集団はこのディレクトリの`*Api.ts`がexportする関数の全部。1つずつ呼び、出た要求を
 * 受け手まで辿る:
 * - 相対パス（同一オリジン）: `app/**\/route.ts`に同じメソッドの口がある。口が管理APIの
 *   転送なら、転送先のbackendの契約（`openapi.json`）にそのメソッドのパスがあり、
 *   **クライアントの待ち時間と口の転送の待ち時間が同じ**（違うと、短い側が先に打ち切り、
 *   長い側を延ばしても症状が変わらない）。本文の有無と項目名も契約と合う。
 * - 絶対URL（backendを直接）: backendの契約にそのメソッドのパスがある。
 *
 * ここで見ないもの:
 * - 口がbackendのどのパスへ渡すか（口ごとの全件） → `app/admin/api/routes.test.ts`
 * - 骨格（失敗時の文言・204・ログ） → `lib/fetchJson.ts`
 * - 応答の解釈など各クライアントが固有に持つもの → 同じディレクトリの`<クライアント名>.test.ts`
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/adminBasicAuth", () => ({
  adminBasicAuthCredentials: () => ({ username: "admin", password: "secret" }),
}));

const SRC = join(__dirname, "../..");
const APP_DIR = join(SRC, "app");
const FRONTEND_ORIGIN = "http://frontend.test";

interface Operation {
  requestBody?: { content: Record<string, { schema: { $ref?: string } }> };
}
interface OpenApi {
  paths: Record<string, Record<string, Operation>>;
  components: { schemas: Record<string, { properties?: Record<string, unknown> }> };
}

const openApi: OpenApi = JSON.parse(readFileSync(join(SRC, "types/generated/openapi.json"), "utf-8"));

function backendOperation(pathname: string, method: string): Operation | undefined {
  for (const [template, operations] of Object.entries(openApi.paths)) {
    const pattern = new RegExp(`^${template.replace(/\{[^}]+\}/g, "[^/]+")}$`);
    if (pattern.test(pathname)) {
      const operation = operations[method.toLowerCase()];
      if (operation) return operation;
    }
  }
  return undefined;
}

function walk(dir: string, accept: (name: string) => boolean): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return walk(full, accept);
    return accept(name) ? [full] : [];
  });
}

/** Next.jsの`app/`規約: `app/a/[b]/route.ts`が`/a/:b`を受ける。 */
const appRoutes = walk(APP_DIR, (name) => name === "route.ts").map((file) => {
  const segments = relative(APP_DIR, file).split(sep).slice(0, -1);
  const names = segments.flatMap((segment) => /^\[(.+)\]$/.exec(segment)?.[1] ?? []);
  const pattern = new RegExp(`^/${segments.map((s) => (/^\[.+\]$/.test(s) ? "([^/]+)" : s)).join("/")}$`);
  return { file, names, pattern };
});

const clientFiles = readdirSync(__dirname).filter((name) => /Api\.ts$/.test(name));

interface Recorded {
  url: string;
  method: string;
  body: string | undefined;
  timeoutMs: number | undefined;
}

const timeouts = new WeakMap<AbortSignal, number>();
let recorded: Recorded[] = [];

async function dispatch(url: string, init: RequestInit = {}): Promise<Response> {
  const method = init.method ?? "GET";
  const body = typeof init.body === "string" ? init.body : undefined;
  recorded.push({ url, method, body, timeoutMs: init.signal ? timeouts.get(init.signal) : undefined });
  if (!url.startsWith("/")) {
    return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
  }
  const { pathname } = new URL(url, FRONTEND_ORIGIN);
  const route = appRoutes.find(({ pattern }) => pattern.test(pathname));
  if (!route) return new Response(null, { status: 404 });
  const handlers: Record<string, unknown> = await import(/* @vite-ignore */ route.file);
  const handler = handlers[method];
  if (typeof handler !== "function") return new Response(null, { status: 405 });
  const values = route.pattern.exec(pathname)!.slice(1).map(decodeURIComponent);
  const params = Object.fromEntries(route.names.map((name, i) => [name, values[i]]));
  return handler(new Request(new URL(url, FRONTEND_ORIGIN), { method, body }), {
    params: Promise.resolve(params),
  });
}

beforeEach(() => {
  recorded = [];
  vi.spyOn(AbortSignal, "timeout").mockImplementation((ms: number) => {
    const signal = new AbortController().signal;
    timeouts.set(signal, ms);
    return signal;
  });
  vi.stubGlobal("fetch", vi.fn(dispatch));
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("管理画面のAPIクライアント", () => {
  it("クライアントのファイルが1つ以上ある", () => {
    expect(clientFiles.length).toBeGreaterThan(0);
  });

  it.each(clientFiles)("%s: exportした関数が叩く先に受け手がいる", async (fileName) => {
    const exported: Record<string, unknown> = await import(/* @vite-ignore */ join(__dirname, fileName));
    const functions = Object.entries(exported).filter(([, value]) => typeof value === "function");
    expect(functions.length).toBeGreaterThan(0);

    for (const [name, fn] of functions) {
      recorded = [];
      const call = fn as (...args: unknown[]) => Promise<unknown>;
      // 引数は区切り文字を含む文字列で埋める。パスへ入る値が符号化されていないと区間が増え、受け手が見つからない。
      await call(...Array(call.length).fill("値/1"));

      const [fromClient, ...forwarded] = recorded;
      expect(fromClient, `${name}が要求を出していない`).toBeDefined();

      if (!fromClient.url.startsWith("/")) {
        const { pathname } = new URL(fromClient.url);
        expect(
          backendOperation(pathname, fromClient.method),
          `${name}: ${fromClient.method} ${pathname}`,
        ).toBeDefined();
        continue;
      }

      // 管理APIの転送でない口（フロント自身が答える`/api/version`等）は、口があれば足りる。
      if (forwarded.length === 0) continue;
      expect(forwarded).toHaveLength(1);
      const [toBackend] = forwarded;
      const operation = backendOperation(new URL(toBackend.url).pathname, toBackend.method);
      expect(operation, `${name}: ${toBackend.method} ${toBackend.url}`).toBeDefined();
      expect(toBackend.timeoutMs, `${name}の待ち時間が口の転送と違う`).toBe(fromClient.timeoutMs);

      const schemaRef = operation!.requestBody?.content["application/json"]?.schema.$ref;
      expect(fromClient.body !== undefined, `${name}の本文の有無が契約と違う`).toBe(
        operation!.requestBody !== undefined,
      );
      const sent: unknown = fromClient.body === undefined ? undefined : JSON.parse(fromClient.body);
      if (schemaRef && typeof sent === "object" && sent !== null) {
        const properties = openApi.components.schemas[schemaRef.split("/").at(-1)!].properties ?? {};
        for (const key of Object.keys(sent)) expect(properties, `${name}の本文の項目${key}`).toHaveProperty(key);
      }
    }
  });
});
