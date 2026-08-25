import type { NextConfig } from "next";
import { BACKEND_INTERNAL_URL } from "./src/lib/backendInternalUrl";

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    // rewritesの外部プロキシ（下記basemap/road-surface-tiles）はデフォルト30秒で打ち切られ、
    // その際「フロントエンド発の500」が返る（next/dist/server/lib/router-utils/proxy-request.js。
    // バックエンドは処理を完走しているのにブラウザだけ500になる）。路面タイルはST_AsMVT化で
    // 通常30秒を大きく下回るようになったが、遠隔DB（Supabase）の一時的な混雑等の外れ値で
    // タイルが「永久の空白」（MapLibreは失敗タイルを再試行しない）になるのを避けるため、
    // 余裕を持たせる。ミリ秒指定。
    proxyTimeout: 60_000,
  },
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
      // 事故レイヤー（外部静的データソース T50）も同じ理由で同一オリジン経由にする。
      {
        source: "/api/region/accident-tiles/:path*",
        destination: `${BACKEND_INTERNAL_URL}/api/region/accident-tiles/:path*`,
      },
      // 停止要因POI・交差点密度レイヤー（改善計画T54）も同じ理由で同一オリジン経由にする。
      {
        source: "/api/region/poi-tiles/:path*",
        destination: `${BACKEND_INTERNAL_URL}/api/region/poi-tiles/:path*`,
      },
    ];
  },
};

export default nextConfig;
