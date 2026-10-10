import type { NextConfig } from "next";
import { BACKEND_INTERNAL_URL } from "./src/lib/backendInternalUrl";

const nextConfig: NextConfig = {
  output: "standalone",
  // e2eのビルド（npm run build:e2e）だけ型を検査しない。型はCIのfrontendジョブのtsc --noEmitが見る
  // （.claude/skills/run-checks/SKILL.md「E2E・画面の撮影の走らせ方」）。
  typescript: { ignoreBuildErrors: process.env.npm_lifecycle_event === "build:e2e" },
  experimental: {
    // rewritesの外部プロキシ（下記のタイル類）は既定で30秒で打ち切り、backendが処理を完走
    // していてもブラウザへは「フロントエンド発の500」を返す（next/dist/server/lib/router-utils/
    // proxy-request.js）。MapLibreは失敗したタイルを再試行しないため、DBの一時的な混雑等で
    // 30秒を超えた外れ値のタイルは空白のまま残る。通常のタイルは30秒を大きく下回るので、
    // 外れ値だけを救う余裕として延ばす。ミリ秒指定。
    proxyTimeout: 60_000,
  },
  // 基礎地図タイルをバックエンド経由でキャッシュしつつ、ブラウザからは常にフロントエンドと
  // 同一オリジンで見えるようにする。タイルとAPI呼び出しを同じバックエンドのオリジンから取ると、
  // ブラウザのオリジン単位の同時接続数上限（HTTP/1.1で6本程度）を大量のタイルリクエストが埋め、
  // ルート生成APIの呼び出しが数十秒詰まる。タイルをフロントエンドのオリジン経由に分離し、
  // APIコールの接続枠と競合しないようにする。
  async rewrites() {
    return [
      {
        source: "/api/basemap/:path*",
        destination: `${BACKEND_INTERNAL_URL}/api/basemap/:path*`,
      },
      // 路面の地域レイヤーもMapLibreのvector sourceとしてパン/ズームのたびに
      // 多数のタイルリクエストが飛ぶため、基礎地図タイルと同じ理由でフロントエンドの
      // 同一オリジン経由にする（バックエンドAPI呼び出しとの接続数競合を避ける）。
      {
        source: "/api/region/road-surface-tiles/:path*",
        destination: `${BACKEND_INTERNAL_URL}/api/region/road-surface-tiles/:path*`,
      },
      // 点のレイヤー（事故・停止要因・補給休憩）も同じ理由で同一オリジン経由にする。
      {
        source: "/api/region/point-tiles/:path*",
        destination: `${BACKEND_INTERNAL_URL}/api/region/point-tiles/:path*`,
      },
      // 土地被覆ラスタタイルも同じ理由で同一オリジン経由にする。
      {
        source: "/api/region/landcover-tiles/:path*",
        destination: `${BACKEND_INTERNAL_URL}/api/region/landcover-tiles/:path*`,
      },
      // JMA動的タイル系レイヤー（降水ナウキャスト等）。ブラウザからJMAの非公式内部API（jma.go.jp）へ
      // 直接取りに行くと、利用者数に比例してJMA側への負荷が増え、同一タイルも毎回JMAへ問い合わせる。
      // 他のタイル系と同じくバックエンド経由（キャッシュ付き）・同一オリジンにする。
      {
        source: "/api/jma-tile/:path*",
        destination: `${BACKEND_INTERNAL_URL}/api/jma-tile/:path*`,
      },
      // 国土地理院 色別標高図タイルも他のタイル系と同じくバックエンド経由
      // （永続ファイルキャッシュ付き）・同一オリジンにする。
      {
        source: "/api/gsi-relief-tile/:path*",
        destination: `${BACKEND_INTERNAL_URL}/api/gsi-relief-tile/:path*`,
      },
    ];
  },
};

export default nextConfig;
