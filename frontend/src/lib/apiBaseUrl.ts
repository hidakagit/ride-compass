// ブラウザからbackendへ到達するためのベースURL。axisCatalogApi.ts/debugStatsApi.ts/
// healthApi.ts/materialCatalogApi.ts/regionApi.ts/routeApi.ts/weatherApi.tsが共有する
// 単一ソース（CLAUDE.md「複雑度平衡」原則の「定数の片側import」）。
//
// サーバー側専用のBACKEND_INTERNAL_URL（backendInternalUrl.ts）とは別物——こちらは
// ブラウザから直接叩くための公開URL（NEXT_PUBLIC_接頭辞）で、Docker Compose環境等で
// サーバー側到達用のURLと値が異なりうる。
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
