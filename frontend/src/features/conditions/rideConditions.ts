/** 走行条件（出発時刻・想定速度）の整形と丸め。
 *
 * **画面部品ではなくここに置く**——値の整形・丸めは「描くもの」の持ち物ではない。
 * 部品に置くと、確かめる側が部品へ口を開けることになる。
 */
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { formatJstMinute, isSameJstDay, jstParts } from "@/lib/time";

const MIN_SPEED_KMH = routeGenerateConfig.min_assumed_speed_kmh;
const MAX_SPEED_KMH = routeGenerateConfig.max_assumed_speed_kmh;

/** 出発時刻の表示ラベル。当日は「9:30」、別日は「9/6 9:30」（日本時間）。 */
export function formatDepartureLabel(time: Date, now: Date = new Date()): string {
  const { month, day, hour } = jstParts(time);
  const hm = `${hour}:${formatJstMinute(time)}`;
  return isSameJstDay(time, now) ? hm : `${month}/${day} ${hm}`;
}

export function clampSpeedKmh(value: number): number {
  if (!Number.isFinite(value)) return routeGenerateConfig.default_assumed_speed_kmh;
  return Math.min(MAX_SPEED_KMH, Math.max(MIN_SPEED_KMH, Math.round(value)));
}
