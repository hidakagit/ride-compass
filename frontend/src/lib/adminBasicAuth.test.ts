// @vitest-environment node
/**
 * `lib/adminBasicAuth.ts`——管理画面の資格情報を環境変数から読む口。
 *
 * 資格情報の環境変数を読むのはこの口だけなので、`vi.stubEnv`で立てて呼ぶ（testing.md「パターン7」）。
 *
 * ここで見ないもの:
 * - 資格情報で画面を守ること → `proxy.test.ts`
 * - 資格情報を転送へ付けること → `app/admin/api/[...path]/route.test.ts`
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { adminBasicAuthCredentials } from "@/lib/adminBasicAuth";

afterEach(() => {
  vi.unstubAllEnvs();
});

function stubCredentials(username: string | undefined, password: string | undefined): void {
  vi.stubEnv("ADMIN_BASIC_AUTH_USERNAME", username);
  vi.stubEnv("ADMIN_BASIC_AUTH_PASSWORD", password);
}

describe("adminBasicAuthCredentials", () => {
  it("両方が設定されていれば、その組を返す", () => {
    stubCredentials("admin", "secret");

    expect(adminBasicAuthCredentials()).toEqual({ username: "admin", password: "secret" });
  });

  it.each([
    ["ユーザー名が無い", undefined, "secret"],
    ["ユーザー名が空", "", "secret"],
    ["パスワードが無い", "admin", undefined],
    ["パスワードが空", "admin", ""],
  ])("%sなら、認証を成立させない（null）", (_scene, username, password) => {
    stubCredentials(username, password);

    expect(adminBasicAuthCredentials()).toBeNull();
  });
});
