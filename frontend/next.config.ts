import type { NextConfig } from "next";

// サーバー側（Next.jsプロセス自身）からバックエンドに到達するためのURL。
// ブラウザ向けのNEXT_PUBLIC_API_URLとは別物（Docker Composeではサービス名で到達する必要があるため）。
const BACKEND_INTERNAL_URL = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // 基礎地図タイルをバックエンド経由でキャッシュしつつ、ブラウザからは常にフロントエンドと
  // 同一オリジン（localhost:3000）で見えるようにする。地図タイルをAPI呼び出しと別オリジンの
  // tiles.openfreemap.orgから直接取得していた頃と違い、両方をバックエンドの同一オリジンから
  // 取得するようにした結果、ブラウザのオリジン単位の同時接続数上限（HTTP/1.1で6本程度）を
  // 大量のタイルリクエストが埋めてしまい、ルート生成APIの呼び出しが数十秒詰まる問題が
  // 実機確認で発覚した。タイルをフロントエンドのオリジン経由に分離し、APIコールの接続枠と
  // 競合しないようにする。
  async rewrites() {
    return [
      {
        source: "/api/basemap/:path*",
        destination: `${BACKEND_INTERNAL_URL}/api/basemap/:path*`,
      },
      // 路面の地域レイヤー（Step10）もMapLibreのvector sourceとしてパン/ズームのたびに
      // 多数のタイルリクエストが飛ぶため、基礎地図タイルと同じ理由でフロントエンドの
      // 同一オリジン経由にする（バックエンドAPI呼び出しとの接続数競合を避ける）。
      {
        source: "/api/region/road-surface-tiles/:path*",
        destination: `${BACKEND_INTERNAL_URL}/api/region/road-surface-tiles/:path*`,
      },
    ];
  },
};

export default nextConfig;
