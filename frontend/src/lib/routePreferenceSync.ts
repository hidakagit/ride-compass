import type { RoutePreferenceWeights } from "@/types/route";

// route_preferenceのキー集合を軸カタログに合わせて補正する（改善計画T269・T302・T303）。
// backendのroute_preference検証は「上書きするなら既知の全axis_idを明示する」方針
// （キー完全一致、backend/app/api/routers/routes.py）のため、どちら向きのズレを
// 放置してもルート生成が422になる。
// - カタログに新しく現れた軸（軸スタジオがDBへ追加）: 既定重みを補う。
// - カタログから消えた軸（T302、公開軸のunpublish）: そのキーを削除する。
//
// RouteSettingsPanel.tsx（マウント中のみ実行）とpage.tsx（生成リクエスト組み立て時、
// T303: パネル未マウントのままヘッダーの生成ボタンだけを押した経路の穴埋め）の
// 両方から呼ぶ共通ロジック。変更不要ならnullを返す（呼び出し側の「変更があった時だけ
// state更新する」判定に使う）。
export function syncRoutePreferenceKeys(
  routePreference: RoutePreferenceWeights,
  catalogDefaultWeights: RoutePreferenceWeights
): RoutePreferenceWeights | null {
  const catalogAxisIds = new Set(Object.keys(catalogDefaultWeights));
  const missingAxisIds = Object.keys(catalogDefaultWeights).filter((id) => !(id in routePreference));
  const staleAxisIds = Object.keys(routePreference).filter((id) => !catalogAxisIds.has(id));
  if (missingAxisIds.length === 0 && staleAxisIds.length === 0) return null;

  const synced = { ...routePreference };
  for (const id of missingAxisIds) synced[id] = catalogDefaultWeights[id];
  for (const id of staleAxisIds) delete synced[id];
  return synced;
}
