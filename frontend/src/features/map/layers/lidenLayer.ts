// 気象庁 雷放電位置データ（liden）の時刻一覧・GeoJSON取得。
//
// 雷・竜巻と同じtargetTimes_N3.json由来だが、lidenは5分おきの全エントリに存在する。
// また、他の動的気象要素が既に取得済みのデータから描画内容を組み立てるのに対し、lidenは
// 実際の落雷地点そのもの（配信元がGeoJSONで提供）を選択フレームごとに個別取得する——
// フレームの切り替えに追従して都度fetchするのはこの要素だけの性質のため、
// features/map/useDynamicWeatherLayers.ts側に専用のfetch effectを持つ。

import {
  fetchJmaNowcastFrames,
  jmaDelivery,
  jmaElementUrl,
  type JmaNowcastFrame,
} from "@/features/map/layers/jmaNowcastFrames";
import { fetchJson } from "@/lib/fetchJson";
import { DEFAULT_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

export function fetchLidenFrames(): Promise<JmaNowcastFrame[]> {
  return fetchJmaNowcastFrames("disaster/liden", "雷放電位置データ");
}

/** 落雷ごとの強弱を示す値を配信元が持たないため、gridMarkのicon-size式が必須で参照する
 * プロパティを満たすための固定値。描き方の宣言（`features/map/scene/groups/weather.ts`）も
 * この定数を参照する。 */
export const LIDEN_MARK_VALUE_PROPERTY = "value";

/** そのフレームの落雷地点。 */
export async function fetchLidenGeojson(frame: JmaNowcastFrame): Promise<GeoJSON.FeatureCollection> {
  const { id: jmaElement, pathGroup } = jmaDelivery("disaster/liden");
  const url = jmaElementUrl(
    { group: pathGroup, element: jmaElement, basetime: frame.basetime, member: "none", validtime: frame.validtime },
    `data.geojson?id=${jmaElement}`,
  );
  const geojson = await fetchJson<GeoJSON.FeatureCollection>(url, {
    timeoutMs: DEFAULT_API_TIMEOUT_MS,
    category: "api:liden",
    errorLabel: "雷放電位置データ",
  });
  return {
    ...geojson,
    features: geojson.features.map((feature) => ({
      ...feature,
      properties: { ...feature.properties, [LIDEN_MARK_VALUE_PROPERTY]: 1 },
    })),
  };
}
