import { timingSafeEqual } from "node:crypto";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// /admin（軸スタジオ・研究/開発者ツール、改善計画T270）のルーティング境界での認可
// （改善計画T272）。Next.js 16でmiddleware.tsはproxy.tsへ改称された（本ファイル名は
// フレームワークの規約、frontend/AGENTS.md「このNext.jsは知っているものと違う」参照）。
//
// HTTP Basic認証（ブラウザ標準ダイアログ）で/adminページ本体（研究/開発者ツールを含む
// UIシェル全体）への到達自体を防ぐ。軸スタジオの管理API呼び出し（axisAdminApi.ts、
// backendの別オリジンへ直接飛ぶためこのProxyを経由しない）は別途
// backend/app/api/routers/axis_admin.py: require_admin_basic_authが同じ方式で保護する
// （2箇所独立のBasic認証チェックだが、同じ資格情報[ADMIN_BASIC_AUTH_USERNAME/PASSWORD]を
// 両側のenvへ設定して運用することで実質1つの資格情報として扱う設計、
// docs/architecture.md「T272」節参照）。
//
// ユーザー方針（2026-08-24）: 「将来的にはアカウント制としたいが、現状は動作確認・研究用
// のためBasic認証として後から拡張する」。未設定（既定、どちらか一方でも空）の環境では
// 常に拒否する（うっかり無保護公開しない、backend側の同種ガードと同じ安全側の既定）。

const REALM = "RideCompass admin";

/** タイミング攻撃を避けるための定数時間比較（レビュー指摘の修正）。backend側
 * require_admin_basic_auth（secrets.compare_digest）と対称にする。
 * timingSafeEqualは長さが異なるバッファでは例外を投げるため、長さが違う場合は
 * その場でfalseを返す（Node公式ドキュメントが案内する標準パターン。文字数の違いは
 * 1文字ずつの内容を漏らす比較そのものより機微度が低いとみなす）。 */
function safeEqual(a: string, b: string): boolean {
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  if (bufA.length !== bufB.length) return false;
  return timingSafeEqual(bufA, bufB);
}

export function proxy(request: NextRequest): NextResponse {
  const expectedUsername = process.env.ADMIN_BASIC_AUTH_USERNAME ?? "";
  const expectedPassword = process.env.ADMIN_BASIC_AUTH_PASSWORD ?? "";

  const unauthorized = () =>
    new NextResponse("認証が必要です", {
      status: 401,
      headers: { "WWW-Authenticate": `Basic realm="${REALM}"` },
    });

  if (expectedUsername === "" || expectedPassword === "") return unauthorized();

  const authHeader = request.headers.get("authorization");
  if (!authHeader?.startsWith("Basic ")) return unauthorized();

  let decoded: string;
  try {
    decoded = atob(authHeader.slice("Basic ".length));
  } catch {
    return unauthorized();
  }
  const separatorIndex = decoded.indexOf(":");
  if (separatorIndex === -1) return unauthorized();
  const username = decoded.slice(0, separatorIndex);
  const password = decoded.slice(separatorIndex + 1);

  if (!safeEqual(username, expectedUsername) || !safeEqual(password, expectedPassword)) return unauthorized();

  return NextResponse.next();
}

export const config = {
  // "/admin"単体（末尾セグメント無し）も確実に含めるため2エントリに分ける
  // （":path*"のゼロ回一致でカバーされる想定だが、明示して取りこぼしを防ぐ）。
  matcher: ["/admin", "/admin/:path*"],
};
