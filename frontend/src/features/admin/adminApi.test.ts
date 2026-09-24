// @vitest-environment node
/**
 * `adminApi.ts`——管理画面のAPIクライアントが叩く先に受け手がいることと、応答や問い合わせを組み立てる部分。
 *
 * 叩く先の母集団はこのファイルがexportする関数の全部。1つずつ呼び、出た要求を受け手まで辿る:
 * - 相対パス: `app/**\/route.ts`に口がある。管理APIの口（`app/admin/api/[...path]`）なら、転送先がbackendの
 *   契約（`openapi.json`）にある同じメソッドの操作で、本文の有無と項目名も契約と合い、**クライアントの待ち時間が
 *   転送の待ち時間を超えない**（超えると転送が先に打ち切り、クライアントを延ばしても症状が変わらない）。
 * - 絶対URL（backendを直接）: backendの契約にそのメソッドのパスがある。
 *
 * ここで見ないもの:
 * - 転送そのもの（資格情報・本文・状態の受け渡し） → `app/admin/api/[...path]/route.test.ts`
 * - 骨格（失敗時の文言・204・ログ） → `lib/fetchJson.ts`
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as adminApi from "./adminApi";
import * as adminRoute from "@/app/admin/api/[...path]/route";
import { ADMIN_PROXY_TIMEOUT_MS } from "@/lib/apiTimeouts";

vi.mock("@/lib/adminBasicAuth", () => ({
  adminBasicAuthCredentials: () => ({ username: "admin", password: "secret" }),
}));

const SRC = join(__dirname, "../..");
const FRONTEND_ORIGIN = "http://frontend.test";

interface Operation {
  requestBody?: { content: Record<string, { schema: { $ref?: string } }> };
}
const openApi: {
  paths: Record<string, Record<string, Operation>>;
  components: { schemas: Record<string, { properties?: Record<string, unknown> }> };
} = JSON.parse(readFileSync(join(SRC, "types/generated/openapi.json"), "utf-8"));

function backendOperation(pathname: string, method: string): Operation | undefined {
  for (const [template, operations] of Object.entries(openApi.paths)) {
    if (new RegExp(`^${template.replace(/\{[^}]+\}/g, "[^/]+")}$`).test(pathname)) {
      const operation = operations[method.toLowerCase()];
      if (operation) return operation;
    }
  }
  return undefined;
}

interface Recorded {
  url: string;
  method: string;
  body: string | undefined;
  timeoutMs: number | undefined;
}
const timeouts = new WeakMap<AbortSignal, number>();
let recorded: Recorded[] = [];
let respond: (url: string) => Response;

async function dispatch(url: string, init: RequestInit = {}): Promise<Response> {
  const method = init.method ?? "GET";
  const body = typeof init.body === "string" ? init.body : undefined;
  recorded.push({ url, method, body, timeoutMs: init.signal ? timeouts.get(init.signal) : undefined });
  if (url.startsWith("/admin/api/")) {
    const handler = (adminRoute as unknown as Record<string, (request: Request) => Promise<Response>>)[method];
    return handler(new Request(new URL(url, FRONTEND_ORIGIN), { method, body }));
  }
  return respond(url);
}

beforeEach(() => {
  recorded = [];
  respond = () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
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

const functions = Object.entries(adminApi).filter(([, value]) => typeof value === "function") as [
  string,
  (...args: unknown[]) => Promise<unknown>,
][];

describe("叩く先", () => {
  it("関数が1つ以上ある", () => {
    expect(functions.length).toBeGreaterThan(0);
  });

  it.each(functions)("%s: 叩く先に受け手がいる", async (name, call) => {
    // 引数は区切り文字を含む文字列で埋める。パスへ入る値が符号化されていないと区間が増え、受け手が見つからない。
    await call(...Array(call.length).fill("値/1"));
    const [fromClient, ...forwarded] = recorded;
    expect(fromClient, `${name}が要求を出していない`).toBeDefined();

    if (!fromClient.url.startsWith("/")) {
      expect(backendOperation(new URL(fromClient.url).pathname, fromClient.method), fromClient.url).toBeDefined();
      return;
    }
    if (!fromClient.url.startsWith("/admin/api/")) {
      // フロント自身が答える口（`/api/version`等）は、口があれば足りる。
      expect(existsSync(join(SRC, "app", new URL(fromClient.url, FRONTEND_ORIGIN).pathname, "route.ts"))).toBe(true);
      return;
    }

    expect(forwarded).toHaveLength(1);
    const [toBackend] = forwarded;
    const operation = backendOperation(new URL(toBackend.url).pathname, toBackend.method);
    expect(operation, `${name}: ${toBackend.method} ${toBackend.url}`).toBeDefined();
    expect(fromClient.timeoutMs!, `${name}の待ち時間が転送より長い`).toBeLessThanOrEqual(ADMIN_PROXY_TIMEOUT_MS);

    expect(fromClient.body !== undefined, `${name}の本文の有無が契約と違う`).toBe(operation!.requestBody !== undefined);
    const schemaRef = operation!.requestBody?.content["application/json"]?.schema.$ref;
    const sent: unknown = fromClient.body === undefined ? undefined : JSON.parse(fromClient.body);
    if (schemaRef && typeof sent === "object" && sent !== null) {
      const properties = openApi.components.schemas[schemaRef.split("/").at(-1)!].properties ?? {};
      for (const key of Object.keys(sent)) expect(properties, `${name}の本文の項目${key}`).toHaveProperty(key);
    }
  });
});

function answer(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      recorded.push({ url, method: "GET", body: undefined, timeoutMs: undefined });
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
}

describe("fetchMapBandsOfThresholds", () => {
  it("地図で段にならない境界と、地図の各段が入力のどの段に当たるかを返す", async () => {
    answer({ dropped_on_map: [2], bands_on_map: [0, 2] });
    const request = {
      axis_id: "a",
      shape: { kind: "categorical" as const, material: "m", mapping: {} },
      thresholds: [1, 2],
    };
    await expect(adminApi.fetchMapBandsOfThresholds(request)).resolves.toEqual({
      droppedOnMap: [2],
      bandsOnMap: [0, 2],
    });
  });
});

describe("getRecentLogs", () => {
  it("指定した絞り込みだけを問い合わせへ付け、ログ行をそのまま返す", async () => {
    answer(["line 1", "line 2"]);
    await expect(adminApi.getRecentLogs({ limit: 200, contains: "jma tile", min_level: "WARNING" })).resolves.toEqual([
      "line 1",
      "line 2",
    ]);
    const query = new URL(recorded[0].url, FRONTEND_ORIGIN).searchParams;
    expect(Object.fromEntries(query)).toEqual({ limit: "200", contains: "jma tile", min_level: "WARNING" });
  });

  it("絞り込みが無い・空文字なら問い合わせを付けない（backendの既定＝保持している全件）", async () => {
    answer([]);
    await adminApi.getRecentLogs();
    await adminApi.getRecentLogs({ contains: "" });
    expect(recorded.map((r) => r.url).filter((url) => url.includes("?"))).toEqual([]);
  });
});

describe("checkBackendHealth", () => {
  it("backendが status: ok を返したときだけ真で、ほかの応答も通信の失敗も偽（例外にしない）", async () => {
    answer({ status: "ok" });
    await expect(adminApi.checkBackendHealth()).resolves.toBe(true);
    answer({ status: "degraded" });
    await expect(adminApi.checkBackendHealth()).resolves.toBe(false);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    await expect(adminApi.checkBackendHealth()).resolves.toBe(false);
  });
});
