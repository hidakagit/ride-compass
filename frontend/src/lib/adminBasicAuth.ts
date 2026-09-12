// 管理画面（/admin配下のBasic認証、proxy.ts）とbackend管理APIへの転送（adminApiProxy.ts）が
// 共有する資格情報。どちらも同じ環境変数を見るため、読み取りと「未設定の扱い」をここ1箇所に置く。

export interface AdminBasicAuthCredentials {
  username: string;
  password: string;
}

/** 環境変数から資格情報を読む。未設定なら`null`（呼び出し側は認証を成立させない）。 */
export function adminBasicAuthCredentials(): AdminBasicAuthCredentials | null {
  return resolveAdminBasicAuth(
    process.env.ADMIN_BASIC_AUTH_USERNAME,
    process.env.ADMIN_BASIC_AUTH_PASSWORD,
  );
}

/**
 * 上記の判断そのもの。`process.env`に触らず引数だけで決まる。
 *
 * 片方でも空なら`null`を返す——「ユーザー名だけ設定された」状態で空パスワードの認証が
 * 通ってしまうのを防ぐ（安全側に倒す）。判断をこちら側へ出すのは、`process.env`が
 * テストファイルをまたいで共有されるため（docs/testing.md参照）。
 */
export function resolveAdminBasicAuth(
  username: string | undefined,
  password: string | undefined,
): AdminBasicAuthCredentials | null {
  if (!username || !password) return null;
  return { username, password };
}
