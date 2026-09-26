// 管理画面（/admin配下のBasic認証、proxy.ts）とbackend管理APIへの転送（`app/admin/api/[...path]/route.ts`）が
// 共有する資格情報。どちらも同じ環境変数を見るため、読み取りと「未設定の扱い」をここ1箇所に置く。

interface AdminBasicAuthCredentials {
  username: string;
  password: string;
}

/**
 * 環境変数から資格情報を読む。未設定なら`null`（呼び出し側は認証を成立させない）。
 *
 * 片方でも空なら`null`を返す——「ユーザー名だけ設定された」状態で空パスワードの認証が
 * 通ってしまうのを防ぐ（安全側に倒す）。
 */
export function adminBasicAuthCredentials(): AdminBasicAuthCredentials | null {
  const username = process.env.ADMIN_BASIC_AUTH_USERNAME;
  const password = process.env.ADMIN_BASIC_AUTH_PASSWORD;
  if (!username || !password) return null;
  return { username, password };
}
