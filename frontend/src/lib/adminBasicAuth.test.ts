// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { adminBasicAuthCredentials } from "./adminBasicAuth";

// 「環境変数がどう揃っていれば資格情報として成立するか」の唯一の検証場所。この環境変数を読むのは
// このモジュールだけで、使う側のテストはモジュールごとモックするため、環境変数を立てても
// 他のファイルの期待値は変わらない（docs/conventions/testing.md「環境変数に依存する挙動のテスト」）。
afterEach(() => {
  vi.unstubAllEnvs();
});

function credentialsWith(username: string | undefined, password: string | undefined) {
  vi.stubEnv("ADMIN_BASIC_AUTH_USERNAME", username);
  vi.stubEnv("ADMIN_BASIC_AUTH_PASSWORD", password);
  return adminBasicAuthCredentials();
}

describe("adminBasicAuthCredentials", () => {
  it("両方揃っていれば資格情報になる", () => {
    expect(credentialsWith("admin", "s3cret")).toEqual({ username: "admin", password: "s3cret" });
  });

  it("両方未設定なら成立しない", () => {
    expect(credentialsWith(undefined, undefined)).toBeNull();
  });

  it("ユーザー名だけ設定されていても成立しない（空パスワードで認証を通さない）", () => {
    expect(credentialsWith("admin", undefined)).toBeNull();
    expect(credentialsWith("admin", "")).toBeNull();
  });

  it("パスワードだけ設定されていても成立しない", () => {
    expect(credentialsWith(undefined, "s3cret")).toBeNull();
    expect(credentialsWith("", "s3cret")).toBeNull();
  });
});
