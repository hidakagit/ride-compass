// 気象庁 雷ナウキャスト・竜巻発生確度ナウキャストのタイル・時刻一覧クライアント。
//
// precipitationNowcast.tsと同じbosai/jmatile/data/nowc/系だが、降水がN1（実況）/
// N2（予測）の2ファイルに分かれているのに対し、雷・竜巻はtargetTimes_N3.json 1本に
// 実況〜60分先の予測が同居する（古いbasetimeの行はvalidtime===basetimeの実況のみ、
// 最新basetimeの行だけvalidtime>basetimeの予測が10分刻みで複数並ぶ）。
// elements配列に雷（thns/thns_nd）・竜巻（trns/trns_nd）の両方が含まれるため、時刻一覧の
// 取得は1回で両方をカバーする（thunderFrames/tornadoFramesは同じ時刻一覧を共有する）。
//
// 雷・竜巻は「回避一択」の危険のため評価軸には組み込まず、rasterTile表現（気象庁が
// 生成した画像をそのまま重ねる）のみを持つ警告表示として扱う。

import type { DynamicWeatherFrame, DynamicWeatherRenderPayload } from "@/components/Map/dynamicWeather";
import {
  jmaDelivery,
  fetchJmaTargetTimes,
  jmaTilePayload,
  parseValidtime,
  type JmaNowcastFrame,
} from "@/components/Map/jmaNowcastFrames";

export type ThunderNowcastFrame = JmaNowcastFrame;

/** 雷・竜巻共通の時刻一覧を取得する（1回のfetchで両方をカバー）。
 * targetTimes_N3.jsonは5分おきにエントリを持つが、雷・竜巻(thns/trns)自体は10分おきにしか
 * 更新されない——5分ズレたエントリは"elements": ["liden"]（雷放電位置データのみ）しか
 * 持たず、thns/trnsのタイルが存在しない。elementsに"thns"（"trns"も常に同じエントリへ
 * 同居するため代表して"thns"だけ見ればよい）を含むエントリだけへ絞り込んでから使う。 */
export async function fetchThunderNowcastFrames(): Promise<ThunderNowcastFrame[]> {
  const raw = await fetchJmaTargetTimes(jmaDelivery("disaster/thunder"), "雷ナウキャスト");
  const thunderElement = jmaDelivery("disaster/thunder").id;
  const withThunderData = raw.filter((t) => t.elements?.includes(thunderElement));
  const frames: ThunderNowcastFrame[] = withThunderData.map((t) => ({ ...t, isForecast: t.validtime > t.basetime }));
  frames.sort((a, b) => a.validtime.localeCompare(b.validtime));
  return frames;
}

/** dynamicWeather.tsの共通フレーム列へ変換する（windFrames/windRenderPayloadと同型、
 * refはframes内のindex）。雷・竜巻のどちらの表示もこの同じフレーム列を共有する。 */
export function thunderFrames(frames: readonly ThunderNowcastFrame[]): DynamicWeatherFrame<number>[] {
  return frames.map((frame, index) => ({ time: parseValidtime(frame.validtime), ref: index }));
}

function nowcastPayload(
  key: "disaster/thunder" | "disaster/tornado",
  frames: readonly ThunderNowcastFrame[],
  ref: number,
): DynamicWeatherRenderPayload | undefined {
  const frame = frames[ref];
  return frame
    ? jmaTilePayload(key, { basetime: frame.basetime, member: "none", validtime: frame.validtime })
    : undefined;
}

/** thunderFramesが返したref（frames内のindex）から、雷ナウキャストの描画ペイロードを
 * 組み立てる（rasterTile、気象庁配信の画像タイルをそのまま重ねる）。 */
export function thunderRenderPayload(
  frames: readonly ThunderNowcastFrame[],
  ref: number,
): DynamicWeatherRenderPayload | undefined {
  return nowcastPayload("disaster/thunder", frames, ref);
}

/** thunderFramesと同じフレーム列・同じrefで、竜巻発生確度ナウキャストの描画ペイロードを
 * 組み立てる（要素だけが雷と違う）。 */
export function tornadoRenderPayload(
  frames: readonly ThunderNowcastFrame[],
  ref: number,
): DynamicWeatherRenderPayload | undefined {
  return nowcastPayload("disaster/tornado", frames, ref);
}
