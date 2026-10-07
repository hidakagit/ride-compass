/**
 * `features/admin/adminApi.ts`——管理画面のAPIクライアントが叩く先に受け手がいることと、backendへの疎通の判定。
 * 機能のクライアントと`app/`の口の両方を読むので、両方より上の`app/`に置く（機能は`app/`を読まない）。
 *
 * 叩く先の母集団はこのファイルがexportする関数の全部。1つずつ呼び、出た要求を受け手まで辿る:
 * - 画面と同じオリジン: `app/**\/route.ts`に口がある。管理APIの口（`app/admin/api/[...path]`）なら、転送先がbackendの
 *   契約（`openapi.json`）にある同じメソッドの操作で、本文の有無と項目名も契約と合い、**クライアントの待ち時間が
 *   転送の待ち時間を超えない**（超えると転送が先に打ち切り、クライアントを延ばしても症状が変わらない）。
 * - 別のオリジン（backendを直接）: backendの契約にそのメソッドのパスがある。
 *
 * 画面と同じオリジンの口は相対パスで呼ぶので、ブラウザと同じく相対パスを解決できるDOMの環境で動かす。
 *
 * ここで見ないもの:
 * - 転送そのもの（資格情報・本文・状態の受け渡し） → `app/admin/api/[...path]/route.test.ts`
 * - 骨格（失敗時の文言・204・ログ） → `lib/apiClient.ts`
 * - 判断の無い詰め替え（応答の項目名・問い合わせの絞り込み） → 使う側（`useMapBandsOfThresholds.test.ts`・`BackendLogsPanel.test.tsx`）が網の層で見る
 */
import { existsSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as adminApi from "@/features/admin/adminApi";
import * as adminRoute from "@/app/admin/api/[...path]/route";
import { ADMIN_PROXY_TIMEOUT_MS } from "@/lib/apiTimeouts";
import { openApi } from "@/testing/openApi";

vi.mock("@/lib/adminBasicAuth", () => ({
  adminBasicAuthCredentials: () => ({ username: "admin", password: "secret" }),
}));

const SRC = join(__dirname, "../..");

interface Operation {
  requestBody?: { content: Record<string, { schema: { $ref?: string } }> };
}

function backendOperation(pathname: string, method: string): Operation | undefined {
  for (const [template, operations] of Object.entries(openApi.paths as Record<string, Record<string, Operation>>)) {
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
/** 直前に作られた待ち時間の印の長さ。要求は1つずつ出るので、出た時点の値がその要求の待ち時間。 */
let lastTimeoutMs: number | undefined;
let recorded: Recorded[] = [];

async function dispatch(input: Request | string, init?: RequestInit): Promise<Response> {
  const request = typeof input === "string" ? new Request(input, init) : input;
  const text = await request.text();
  const body = text === "" ? undefined : text;
  const { method, url } = request;
  recorded.push({ url, method, body, timeoutMs: lastTimeoutMs });
  if (new URL(url).pathname.startsWith("/admin/api/")) {
    const handler = (adminRoute as unknown as Record<string, (request: Request) => Promise<Response>>)[method];
    return handler(new Request(url, { method, body }));
  }
  return Response.json({});
}

beforeEach(() => {
  recorded = [];
  lastTimeoutMs = undefined;
  vi.spyOn(AbortSignal, "timeout").mockImplementation((ms: number) => {
    lastTimeoutMs = ms;
    return new AbortController().signal;
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

    const { origin, pathname } = new URL(fromClient.url);
    if (origin !== window.location.origin) {
      expect(backendOperation(pathname, fromClient.method), fromClient.url).toBeDefined();
      return;
    }
    if (!pathname.startsWith("/admin/api/")) {
      // フロント自身が答える口（`/api/version`等）は、口があれば足りる。
      expect(existsSync(join(SRC, "app", pathname, "route.ts"))).toBe(true);
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
    vi.fn(async () => Response.json(body)),
  );
}

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
