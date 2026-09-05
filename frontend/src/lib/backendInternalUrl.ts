// サーバー側（Next.jsプロセス自身）からbackendへ到達するためのURL。ブラウザ向けの
// NEXT_PUBLIC_API_URLとは別物（Docker Composeではサービス名で到達する必要があるため、
// 混同すると本番でbasemapタイルが502になりうる）。next.config.ts（rewritesの
// basemap/road-surface-tiles等プロキシ）とadminApiProxy.ts（軸CRUD管理APIのプロキシ）が
// この単一ソースを共有する。
//
// next.config.tsからは相対importで参照する（next.config.tsはNext.jsのパスエイリアス
// [@/...]が確立する前にNode標準のモジュール解決で読み込まれるため、"@/lib/..."は使えない）。
export const BACKEND_INTERNAL_URL = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";
