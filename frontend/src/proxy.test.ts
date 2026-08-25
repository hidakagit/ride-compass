// @vitest-environment node
// /admin配下を保護するBasic認証ミドルウェア（proxy.ts）のテスト。DOM操作は不要なため
// node環境で実行する（vitest.config.mts参照）。
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { proxy } from "./proxy";

const ADMIN_URL = "https://example.com/admin";

function basicAuthHeader(username: string, password: string): string {
  return `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`;
}

function requestWithAuth(authorization?: string): NextRequest {
  return new NextRequest(ADMIN_URL, {
    headers: authorization === undefined ? undefined : { authorization },
  });
}

// テスト間でprocess.envを汚染しないよう、都度退避・復元する。
const ORIGINAL_ENV = { ...process.env };

function resetEnv() {
  delete process.env.ADMIN_BASIC_AUTH_USERNAME;
  delete process.env.ADMIN_BASIC_AUTH_PASSWORD;
}

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

describe("proxy", () => {
  describe("環境変数未設定（安全側デフォルト）", () => {
    beforeEach(() => resetEnv());

    it("ADMIN_BASIC_AUTH_USERNAME/PASSWORDが両方未設定のとき401を返す", () => {
      const response = proxy(requestWithAuth(basicAuthHeader("admin", "secret")));
      expect(response.status).toBe(401);
    });

    it("ADMIN_BASIC_AUTH_USERNAMEのみ設定（PASSWORD未設定）のとき401を返す", () => {
      process.env.ADMIN_BASIC_AUTH_USERNAME = "admin";
      const response = proxy(requestWithAuth(basicAuthHeader("admin", "secret")));
      expect(response.status).toBe(401);
    });

    it("ADMIN_BASIC_AUTH_PASSWORDのみ設定（USERNAME未設定）のとき401を返す", () => {
      process.env.ADMIN_BASIC_AUTH_PASSWORD = "secret";
      const response = proxy(requestWithAuth(basicAuthHeader("admin", "secret")));
      expect(response.status).toBe(401);
    });

    it("401レスポンスにはWWW-Authenticateヘッダ（Basic realm）が付く", () => {
      const response = proxy(requestWithAuth(basicAuthHeader("admin", "secret")));
      expect(response.headers.get("WWW-Authenticate")).toBe('Basic realm="RideCompass admin"');
    });
  });

  describe("環境変数設定済みでの認証チェック", () => {
    beforeEach(() => {
      resetEnv();
      process.env.ADMIN_BASIC_AUTH_USERNAME = "admin";
      process.env.ADMIN_BASIC_AUTH_PASSWORD = "s3cret";
    });

    it("Authorizationヘッダが無い場合401", () => {
      const response = proxy(requestWithAuth(undefined));
      expect(response.status).toBe(401);
    });

    it("Authorizationヘッダが'Basic 'で始まらない場合401", () => {
      const response = proxy(requestWithAuth("Bearer abcdef"));
      expect(response.status).toBe(401);
    });

    it("Base64デコード失敗（不正な値）でも例外を投げず401を返す", () => {
      expect(() => proxy(requestWithAuth("Basic ***not-valid-base64***"))).not.toThrow();
      const response = proxy(requestWithAuth("Basic ***not-valid-base64***"));
      expect(response.status).toBe(401);
    });

    it("デコード後の値に':'区切りが無い場合401", () => {
      const noColon = Buffer.from("adminsecretwithoutcolon").toString("base64");
      const response = proxy(requestWithAuth(`Basic ${noColon}`));
      expect(response.status).toBe(401);
    });

    it("ユーザー名は正しいがパスワードが違う場合401", () => {
      const response = proxy(requestWithAuth(basicAuthHeader("admin", "wrong-password")));
      expect(response.status).toBe(401);
    });

    it("パスワードは正しいがユーザー名が違う場合401", () => {
      const response = proxy(requestWithAuth(basicAuthHeader("wrong-user", "s3cret")));
      expect(response.status).toBe(401);
    });

    it("長さの異なるユーザー名/パスワード（safeEqualのtimingSafeEqualラッパー経由）でも例外を投げず401を返す", () => {
      // 期待値("admin"/"s3cret")よりずっと短い・長い値を与え、safeEqual内のtimingSafeEqualが
      // 長さ不一致のバッファに対して例外を投げないこと（事前の長さチェックで弾かれること）を
      // 間接的に確認する。
      expect(() => proxy(requestWithAuth(basicAuthHeader("a", "s")))).not.toThrow();
      expect(proxy(requestWithAuth(basicAuthHeader("a", "s"))).status).toBe(401);

      const veryLongUsername = "admin".repeat(50);
      const veryLongPassword = "s3cret".repeat(50);
      expect(() => proxy(requestWithAuth(basicAuthHeader(veryLongUsername, veryLongPassword)))).not.toThrow();
      expect(proxy(requestWithAuth(basicAuthHeader(veryLongUsername, veryLongPassword))).status).toBe(401);
    });

    it("正しい資格情報のときのみNextResponse.next()相当（x-middleware-nextヘッダ付き・200）を返す", () => {
      const response = proxy(requestWithAuth(basicAuthHeader("admin", "s3cret")));
      expect(response.status).toBe(200);
      expect(response.headers.get("x-middleware-next")).toBe("1");
      expect(response.headers.get("WWW-Authenticate")).toBeNull();
    });
  });
});
