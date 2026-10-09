import { backendApi, getOptions, requestApi } from "@/lib/apiClient";
import { DEFAULT_API_TIMEOUT_MS } from "@/lib/apiTimeouts";
import type { Coordinates, PlaceCandidate } from "@/types/route";

/** 文字列から地点の候補を引く。施設は`near`に近い順に並ぶ。対象範囲を読めない等で使えないときは、backendの文（「対象範囲を読めませんでした」）で投げる。 */
export async function searchPlaces(query: string, near: Coordinates): Promise<PlaceCandidate[]> {
  const data = await requestApi(
    (init) =>
      backendApi.GET("/api/place-search", {
        params: { query: { q: query, latitude: near.latitude, longitude: near.longitude } },
        ...init,
      }),
    getOptions({ timeoutMs: DEFAULT_API_TIMEOUT_MS, category: "api:placeSearch", errorLabel: "地点の検索" }),
  );
  return data.candidates;
}
