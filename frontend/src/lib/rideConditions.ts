/** 走行条件（出発時刻・想定速度）の整形と丸め。
 *
 * **画面部品ではなくここに置く**——値の整形・丸めは「描くもの」の持ち物ではない。
 * 部品に置くと、確かめる側が部品へ口を開けることになる。
 */
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

const MIN_SPEED_KMH = routeGenerateConfig.min_assumed_speed_kmh;
const MAX_SPEED_KMH = routeGenerateConfig.max_assumed_speed_kmh;

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/** 出発時刻の表示ラベル。当日は「9:30」、別日は「9/6 9:30」（ローカル時刻）。 */
export function formatDepartureLabel(time: Date, now: Date = new Date()): string {
  const hm = `${time.getHours()}:${pad2(time.getMinutes())}`;
  const sameDay =
    time.getFullYear() === now.getFullYear() && time.getMonth() === now.getMonth() && time.getDate() === now.getDate();
  return sameDay ? hm : `${time.getMonth() + 1}/${time.getDate()} ${hm}`;
}

/** input[type=datetime-local]のvalue形式（タイムゾーン無しのYYYY-MM-DDTHH:mm、
 * ローカル時刻）。この形式の文字列はnew Date()がローカル時刻として解釈するため、
 * 変換は往路（Date→この形式）だけ用意すればよい。 */
export function toDatetimeLocalValue(time: Date): string {
  return `${time.getFullYear()}-${pad2(time.getMonth() + 1)}-${pad2(time.getDate())}T${pad2(time.getHours())}:${pad2(time.getMinutes())}`;
}

export function clampSpeedKmh(value: number): number {
  if (!Number.isFinite(value)) return routeGenerateConfig.default_assumed_speed_kmh;
  return Math.min(MAX_SPEED_KMH, Math.max(MIN_SPEED_KMH, Math.round(value)));
}
