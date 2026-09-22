// backendのadmin API群（`/api/admin/**`、いずれもHTTP Basic認証必須）への
// サーバー側プロキシ。
// `frontend/src/app/admin/api/`配下の各route handlerからのみ呼ぶこと（route handlerは常に
// サーバー側実行のため、"use client"コンポーネントから直接importしない限り
// ADMIN_BASIC_AUTH_PASSWORD等がブラウザバンドルへ漏れる心配はない）。
//
// ブラウザは/adminで入力したBasic認証情報を別オリジンのbackendへ自動転送しないため、
// クライアント側のJSはbackendを直接叩かず、この一群のroute handler（`/admin/api/...`、
// proxy.tsのmatcher`/admin/:path*`に含まれるパス）を経由する。
// ブラウザは/admin読込時に一度Basic認証すれば、同一オリジン・
// 同一realmへの後続リクエストの認証情報を自身の認証キャッシュから自動付与する（fetchの
// 既定のcredentialsモード"same-origin"がこれを含む、ブラウザ標準の挙動）ため、クライアント側の
// JSは何もしなくてよい。このNext.jsサーバー（route handler）が、サーバー環境変数
// ADMIN_BASIC_AUTH_USERNAME/PASSWORD（proxy.tsが既に使っている値と同じ、運用上backend側と
// 揃えて設定する既存の方針）からbackend宛のAuthorizationヘッダを組み立てて転送するため、
// backend向けの資格情報はブラウザへ一切露出しない。

import { BACKEND_INTERNAL_URL } from "@/lib/backendInternalUrl";
import { DEFAULT_API_TIMEOUT_MS } from "@/lib/apiTimeouts";
import { adminBasicAuthCredentials } from "@/lib/adminBasicAuth";

function backendAuthHeader(): string | null {
  const credentials = adminBasicAuthCredentials();
  if (credentials === null) return null;
  return `Basic ${Buffer.from(`${credentials.username}:${credentials.password}`).toString("base64")}`;
}

interface ProxyToBackendAdminOptions {
  /** backendへの転送タイムアウト（省略時15秒）。全表走査を伴う集計API等、既定より長く
   * かかることが分かっているエンドポイントだけ個別に延ばす。 */
  timeoutMs?: number;
}

/** `backendPath`（例: "/api/admin/axis-definitions/gradient"）へrequestをそのまま転送し、
 * backendの応答（ステータス・本文）をそのまま返す。GET/POST/PUT/DELETEのいずれも
 * 呼び出し元route handlerがHTTPメソッドを解決してから渡す想定（このヘルパー自体は
 * `request.method`をそのまま使う）。`request.url`のクエリ文字列（例:
 * "?limit=200&contains=jma-tile"）は`backendPath`にそのまま付け足して転送する。 */
export async function proxyToBackendAdmin(
  request: Request,
  backendPath: string,
  options: ProxyToBackendAdminOptions = {},
): Promise<Response> {
  const authHeader = backendAuthHeader();
  if (authHeader === null) {
    return Response.json(
      { detail: "サーバー側の管理者資格情報（ADMIN_BASIC_AUTH_USERNAME/PASSWORD）が未設定です" },
      { status: 500 },
    );
  }

  const hasBody = request.method === "POST" || request.method === "PUT";
  const { search } = new URL(request.url);
  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${BACKEND_INTERNAL_URL}${backendPath}${search}`, {
      method: request.method,
      headers: {
        Authorization: authHeader,
        ...(hasBody ? { "Content-Type": "application/json" } : {}),
      },
      body: hasBody ? await request.text() : undefined,
      signal: AbortSignal.timeout(options.timeoutMs ?? DEFAULT_API_TIMEOUT_MS),
    });
  } catch (error) {
    return Response.json(
      { detail: `backendへの接続に失敗しました: ${error instanceof Error ? error.message : String(error)}` },
      { status: 502 },
    );
  }

  if (backendResponse.status === 204) return new Response(null, { status: 204 });
  const body = await backendResponse.text();
  return new Response(body, {
    status: backendResponse.status,
    headers: { "Content-Type": backendResponse.headers.get("content-type") ?? "application/json" },
  });
}
