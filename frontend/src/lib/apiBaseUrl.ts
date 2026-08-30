// ブラウザからbackendへ到達するためのベースURL（改善計画T425、ゼロベース網羅レビュー指摘）。
// `NEXT_PUBLIC_API_URL ?? "http://localhost:8000"`という同一の1行が
// axisCatalogApi.ts/debugStatsApi.ts/healthApi.ts/materialCatalogApi.ts/regionApi.ts/
// routeApi.ts/weatherApi.tsの7ファイルへ手書きで複製されていた（`backendInternalUrl.ts`
// [サーバー側専用のBACKEND_INTERNAL_URL]と同型の重複、CLAUDE.md「複雑度平衡」原則の
// 「定数の片側import」に反する）ため、単一ソースへ集約する。
//
// サーバー側専用のBACKEND_INTERNAL_URL（backendInternalUrl.ts）とは別物——こちらは
// ブラウザから直接叩くための公開URL（NEXT_PUBLIC_接頭辞）で、Docker Compose環境等で
// サーバー側到達用のURLと値が異なりうる。
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
