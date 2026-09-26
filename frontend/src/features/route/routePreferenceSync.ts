import type { RoutePreferenceWeights } from "@/types/route";

interface CatalogWeights {
  loaded: boolean;
  defaultWeights: RoutePreferenceWeights;
}

/** 重みのキーを軸カタログの公開軸へ揃えた値。backendの`route_preference`の検証はキーの完全一致を求め
 * （`api/routers/routes.py`）、どちら向きにずれても生成が422になる。カタログに増えた軸は既定の重みで補い、
 * 消えた軸（公開を取り下げた軸）は外す。**取得が決まるまでは揃えない**——軸0件のまま揃えると、保存済みの
 * 重みを全部消す。揃える必要が無ければ渡した値をそのまま返す。
 *
 * 画面の重み（重みタブ・送る値・道の評価・結果の表示）はどれもこの関数を1回通した値を読む。 */
export function alignRoutePreference(
  routePreference: RoutePreferenceWeights,
  catalog: CatalogWeights,
): RoutePreferenceWeights {
  if (!catalog.loaded) return routePreference;
  const catalogAxisIds = new Set(Object.keys(catalog.defaultWeights));
  const missingAxisIds = [...catalogAxisIds].filter((id) => !(id in routePreference));
  const staleAxisIds = Object.keys(routePreference).filter((id) => !catalogAxisIds.has(id));
  if (missingAxisIds.length === 0 && staleAxisIds.length === 0) return routePreference;

  const aligned = { ...routePreference };
  for (const id of missingAxisIds) aligned[id] = catalog.defaultWeights[id];
  for (const id of staleAxisIds) delete aligned[id];
  return aligned;
}

/** 生成リクエストへ載せる重み（`aligned`は`alignRoutePreference`を通した値）。利用者が重みを上書きしていない
 * 間と、軸カタログを取得できていない間は送らず（null）、backendの既定の重みへ委ねる。 */
export function routePreferenceToSend(
  aligned: RoutePreferenceWeights,
  catalogLoaded: boolean,
  overrideEnabled: boolean,
): RoutePreferenceWeights | null {
  return overrideEnabled && catalogLoaded ? aligned : null;
}
