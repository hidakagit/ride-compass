// コードレビュー指摘の修正: サーバー側（Next.jsプロセス自身）からbackendへ到達するための
// URL。ブラウザ向けのNEXT_PUBLIC_API_URLとは別物（Docker Composeではサービス名で到達する
// 必要があるため）。以前はnext.config.ts（rewritesのbasemap/road-surface-tiles等プロキシ）と
// adminApiProxy.ts（軸CRUD管理APIのプロキシ）でそれぞれ独立に同じ定数を手書きしており、
// 過去に本番でNEXT_PUBLIC_API_URLと混同されbasemapタイルが502になったインシデントの
// 原因になった変数でもある（docs/improvement-plan.md参照）。将来フォールバック値や
// バリデーションを変更する際に片方だけ直し忘れる事故を避けるため、単一ソースへ集約する。
//
// next.config.tsからは相対importで参照する（next.config.tsはNext.jsのパスエイリアス
// [@/...]が確立する前にNode標準のモジュール解決で読み込まれるため、"@/lib/..."は使えない）。
export const BACKEND_INTERNAL_URL = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";
