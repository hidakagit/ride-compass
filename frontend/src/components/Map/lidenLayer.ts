// 気象庁 雷放電位置データ（liden、改善計画T541）のフレーム列・GeoJSON取得。
//
// thunderNowcast.tsと同じtargetTimes_N3.json由来だが、liden自体は5分おきの全エントリに
// 存在する（thns/trnsは10分おきのエントリにしか無い、jmaNowcastFrames.tsのコメント参照）。
// また、他の動的気象要素（gridFill/gridMark）が既に取得済みの格子データから同期的に
// GeoJSONを組み立てるのに対し、lidenは実際の落雷地点そのもの（配信元が既にGeoJSONで
// 提供）を選択フレームごとに個別取得する必要がある——フレームの切り替えに追従して
// 都度fetchするのはこの要素だけの性質のため、hooks/useDynamicWeatherLayers.ts側に
// 専用のfetch effectを持つ（他要素のuseMemoだけで完結する構成とは異なる）。

import type { DynamicWeatherFrame } from "@/components/Map/dynamicWeather";
import { JMA_TILE_BASE_URL, fetchJmaTargetTimes, parseValidtime, type JmaNowcastFrame } from "@/components/Map/jmaNowcastFrames";
import { fetchJson } from "@/lib/fetchJson";

export type LidenFrame = JmaNowcastFrame;

const TARGET_TIMES_N3_URL = `${JMA_TILE_BASE_URL}/jmatile/data/nowc/targetTimes_N3.json`;

/** liden（雷放電位置データ）のフレーム時刻一覧を取得する。 */
export async function fetchLidenFrames(): Promise<LidenFrame[]> {
  const raw = await fetchJmaTargetTimes(TARGET_TIMES_N3_URL, "雷放電位置データ");
  const withLidenData = raw.filter((t) => t.elements?.includes("liden"));
  const frames: LidenFrame[] = withLidenData.map((t) => ({ ...t, isForecast: t.validtime > t.basetime }));
  frames.sort((a, b) => a.validtime.localeCompare(b.validtime));
  return frames;
}

/** dynamicWeather.tsの共通フレーム列へ変換する（thunderFramesと同型、refはframes内のindex）。 */
export function lidenFrames(frames: readonly LidenFrame[]): DynamicWeatherFrame<number>[] {
  return frames.map((frame, index) => ({ time: parseValidtime(frame.validtime), ref: index }));
}

function lidenGeojsonUrl(frame: LidenFrame): string {
  return `${JMA_TILE_BASE_URL}/jmatile/data/nowc/${frame.basetime}/none/${frame.validtime}/surf/liden/data.geojson?id=liden`;
}

/** 落雷ごとの強弱を示す値を配信元が持たないため、DynamicWeatherMarkSpec.valueProperty
 * （gridMarkのicon-size式が必須で参照するプロパティ）を満たすための固定値。
 * MapView.tsx側のgridMarkスペック定義（valueProperty）もこの定数を参照する。 */
export const LIDEN_MARK_VALUE_PROPERTY = "value";

/** lidenFramesが返したref（frames内のindex）に対応する実際の落雷地点GeoJSONを取得する。
 * 他要素のRenderPayload組み立て関数と異なり、既に手元にあるデータからではなく配信元へ
 * 都度fetchするため非同期。frameが無ければ（refが範囲外）undefinedを返す。 */
export async function fetchLidenGeojson(
  frames: readonly LidenFrame[],
  ref: number
): Promise<GeoJSON.FeatureCollection | undefined> {
  const frame = frames[ref];
  if (!frame) return undefined;
  const geojson = await fetchJson<GeoJSON.FeatureCollection>(lidenGeojsonUrl(frame), {
    timeoutMs: 15000,
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
