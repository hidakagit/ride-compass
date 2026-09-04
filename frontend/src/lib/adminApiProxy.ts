// backendのadmin API群（axis_admin.py・debug_admin.py、いずれもHTTP Basic認証必須）への
// サーバー側プロキシ（改善計画T305、T517で軸CRUD専用から汎用へ改名）。
// `frontend/src/app/admin/api/`配下の各route handlerからのみ呼ぶこと（route handlerは常に
// サーバー側実行のため、"use client"コンポーネントから直接importしない限り
// ADMIN_BASIC_AUTH_PASSWORD等がブラウザバンドルへ漏れる心配はない）。
//
// 以前はブラウザから直接backend（別オリジン）を叩き、ブラウザがproxy.ts分のBasic認証を
// 自動転送しないため、軸スタジオ画面（AxisStudio.tsx）に専用のユーザー名/パスワード入力欄を
// 持っていた。しかし/adminページ自体が既にproxy.tsのBasic認証で保護されており、この画面へ
// 来られた時点でブラウザは既に認証済み——二重ログインを求めるUIが分かりにくいという実機
// フィードバックを受け、この画面用の入力欄を撤去した。
//
// 代わりに、この一群のroute handler（`/admin/api/...`、proxy.tsのmatcher`/admin/:path*`に
// 含まれるパス）を経由する。ブラウザは/admin読込時に一度Basic認証すれば、同一オリジン・
// 同一realmへの後続リクエストの認証情報を自身の認証キャッシュから自動付与する（fetchの
// 既定のcredentialsモード"same-origin"がこれを含む、ブラウザ標準の挙動）ため、クライアント側の
// JSは何もしなくてよい。このNext.jsサーバー（route handler）が、サーバー環境変数
// ADMIN_BASIC_AUTH_USERNAME/PASSWORD（proxy.tsが既に使っている値と同じ、運用上backend側と
// 揃えて設定する既存の方針）からbackend宛のAuthorizationヘッダを組み立てて転送するため、
// backend向けの資格情報はブラウザへ一切露出しない。

import { BACKEND_INTERNAL_URL } from "@/lib/backendInternalUrl";

function backendAuthHeader(): string | null {
  const username = process.env.ADMIN_BASIC_AUTH_USERNAME ?? "";
  const password = process.env.ADMIN_BASIC_AUTH_PASSWORD ?? "";
  if (username === "" || password === "") return null;
  return `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`;
}

const DEFAULT_TIMEOUT_MS = 15000;

export interface ProxyToBackendAdminOptions {
  /** backendへの転送タイムアウト（省略時15秒）。全表走査を伴う集計API等、既定より長く
   * かかることが分かっているエンドポイントだけ個別に延ばす。 */
  timeoutMs?: number;
}

/** `backendPath`（例: "/api/admin/axis-definitions/gradient"）へrequestをそのまま転送し、
 * backendの応答（ステータス・本文）をそのまま返す。GET/POST/PUT/DELETEのいずれも
 * 呼び出し元route handlerがHTTPメソッドを解決してから渡す想定（このヘルパー自体は
 * `request.method`をそのまま使う）。`request.url`のクエリ文字列（例:
 * "?limit=200&contains=jma-tile"）は`backendPath`にそのまま付け足して転送する
 * （T517: `GET /api/admin/debug/logs`の`limit`/`contains`のように、GET系エンドポイントが
 * クエリパラメータを取る場合に必要）。 */
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
      signal: AbortSignal.timeout(options.timeoutMs ?? DEFAULT_TIMEOUT_MS),
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
