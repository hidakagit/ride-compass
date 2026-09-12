// @vitest-environment node
import { describe, expect, it } from "vitest";
import { resolveAdminBasicAuth } from "./adminBasicAuth";

// 「環境変数がどう揃っていれば資格情報として成立するか」の唯一の検証場所。`process.env`に
// 触らずに済むよう、判断は引数だけで決まる純関数へ出してある——`process.env`はテスト
// ファイルをまたいで共有されるため、環境変数を立てて検証すると並行実行中の別ファイルの
// 期待値を静かに書き換える（docs/testing.md「環境変数に依存する挙動のテスト」参照）。
describe("resolveAdminBasicAuth", () => {
  it("両方揃っていれば資格情報になる", () => {
    expect(resolveAdminBasicAuth("admin", "s3cret")).toEqual({ username: "admin", password: "s3cret" });
  });

  it("両方未設定なら成立しない", () => {
    expect(resolveAdminBasicAuth(undefined, undefined)).toBeNull();
  });

  it("ユーザー名だけ設定されていても成立しない（空パスワードで認証を通さない）", () => {
    expect(resolveAdminBasicAuth("admin", undefined)).toBeNull();
    expect(resolveAdminBasicAuth("admin", "")).toBeNull();
  });

  it("パスワードだけ設定されていても成立しない", () => {
    expect(resolveAdminBasicAuth(undefined, "s3cret")).toBeNull();
    expect(resolveAdminBasicAuth("", "s3cret")).toBeNull();
  });
});
