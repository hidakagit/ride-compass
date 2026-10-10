/** 走行条件（出発時刻・想定速度）の整形と丸め。
 *
 * **画面部品ではなくここに置く**——値の整形・丸めは「描くもの」の持ち物ではない。
 * 部品に置くと、確かめる側が部品へ口を開けることになる。
 */
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { formatJstMinute, isSameJstDay, jstParts } from "@/lib/time";

export const MIN_SPEED_KMH = routeGenerateConfig.min_assumed_speed_kmh;
export const MAX_SPEED_KMH = routeGenerateConfig.max_assumed_speed_kmh;

/** 出発時刻として選べる値の刻み。「今」もこの刻みで進む。 */
export const DEPARTURE_STEP_MS = 5 * 60_000;

/** 時刻（ms）を出発時刻の刻みへ切り下げる。 */
export function floorToDepartureStep(ms: number): number {
  return Math.floor(ms / DEPARTURE_STEP_MS) * DEPARTURE_STEP_MS;
}

/** 出発時刻の表示ラベルを、日付と時刻に分けたもの。`now`と同じ日（日本時間）は`["9:30"]`、別日は`["9/6", "9:30"]`。 */
export function departureLabelParts(time: Date, now: Date): string[] {
  const { month, day, hour } = jstParts(time);
  const hm = `${hour}:${formatJstMinute(time)}`;
  return isSameJstDay(time, now) ? [hm] : [`${month}/${day}`, hm];
}

/** 出発時刻の表示ラベル。`now`と同じ日（日本時間）は「9:30」、別日は「9/6 9:30」。 */
export function formatDepartureLabel(time: Date, now: Date): string {
  return departureLabelParts(time, now).join(" ");
}

export function clampSpeedKmh(value: number): number {
  if (!Number.isFinite(value)) return routeGenerateConfig.default_assumed_speed_kmh;
  return Math.min(MAX_SPEED_KMH, Math.max(MIN_SPEED_KMH, Math.round(value)));
}
