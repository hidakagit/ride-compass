// @vitest-environment node
/**
 * `proxy.ts`——管理画面（`/admin`配下。画面と、管理APIへの転送の口）の手前のBasic認証。入口はNext.jsが呼ぶ`proxy`
 * （要求を受けて応答を返す）で、確かめるのは応答（通すか、401で資格情報を求めるか）。
 *
 * ここで見ないもの:
 * - どの道で`proxy`が呼ばれるか（`config.matcher`）→ Next.jsの規約の宣言で、判定はフレームワークが持つ。公式の判定の
 *   道具（`next/experimental/testing/server`）はNext.jsのビルドの部品まで読み込み、このテストの実行方式（vmThreads）では
 *   読み込めない
 * - 資格情報を環境変数から読むこと・片方だけ設定された状態を未設定とみなすこと → `lib/adminBasicAuth.test.ts`。
 *   ここでは読み取り口を差し替えて、設定済み・未設定を与える
 * - 比較が定数時間であること → 応答に現れない（理由は実装の隣のコメントが持つ）
 * - 転送の先でbackendが同じ資格情報を確かめること → backendのテスト
 */
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { adminBasicAuthCredentials } from "@/lib/adminBasicAuth";

import { proxy } from "./proxy";

vi.mock("@/lib/adminBasicAuth", () => ({ adminBasicAuthCredentials: vi.fn() }));

const CREDENTIALS = { username: "admin", password: "s3cret" };

function requestWith(authorization?: string) {
  return new NextRequest("https://ridecompass.test/admin", {
    headers: authorization === undefined ? {} : { authorization },
  });
}

const basic = (userAndPassword: string) => `Basic ${btoa(userAndPassword)}`;

/** 通したなら真。拒んだなら、ブラウザに資格情報のダイアログを出させる応答であることも確かめる。 */
function passed(response: Response): boolean {
  if (response.status === 401) {
    expect(response.headers.get("WWW-Authenticate")).toMatch(/^Basic realm="[^"]+"$/);
    return false;
  }
  expect(response.headers.get("x-middleware-next")).toBe("1");
  return true;
}

describe("proxy（Basic認証）", () => {
  beforeEach(() => {
    vi.mocked(adminBasicAuthCredentials).mockReturnValue(CREDENTIALS);
  });

  it("設定された資格情報と一致すれば通す", () => {
    expect(passed(proxy(requestWith(basic("admin:s3cret"))))).toBe(true);
  });

  it("パスワードに区切りの「:」を含んでも、最初の「:」で分けて照合する", () => {
    vi.mocked(adminBasicAuthCredentials).mockReturnValue({ username: "admin", password: "pa:ss" });

    expect(passed(proxy(requestWith(basic("admin:pa:ss"))))).toBe(true);
  });

  it("資格情報が設定されていない環境では、どんな要求も拒む", () => {
    vi.mocked(adminBasicAuthCredentials).mockReturnValue(null);

    expect(passed(proxy(requestWith(basic("admin:s3cret"))))).toBe(false);
    expect(passed(proxy(requestWith(basic(":"))))).toBe(false);
  });

  it.each([
    ["資格情報が無い", undefined],
    ["Basic以外の方式", "Bearer admin:s3cret"],
    ["Base64として読めない", "Basic %%%"],
    ["ユーザー名とパスワードの区切りが無い", basic("admins3cret")],
    ["ユーザー名が違う", basic("Admin:s3cret")],
    ["パスワードが違う（同じ長さ）", basic("admin:s3creT")],
    ["パスワードが違う（長さが違う）", basic("admin:s3cret!")],
  ])("%sなら拒む", (_, authorization) => {
    expect(passed(proxy(requestWith(authorization)))).toBe(false);
  });
});
