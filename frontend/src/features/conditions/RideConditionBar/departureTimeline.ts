// 出発時刻ピッカー（RideConditionBar）のドラッグタイムライン用の目盛り生成。気象レイヤーの
// 取得結果に依存しない理由と刻みの粒度はdocs/modules/frontend/dynamic-weather-layers.md
// 「共有タイムラインのラベル」節が持つ。
import { formatJstDateTime, formatJstHourMinute, formatJstMinute, jstParts } from "@/lib/time";
import type { DynamicLayerTimeSliderFrame } from "@/features/conditions/DynamicLayerTimeSlider/DynamicLayerTimeSlider";

const FIVE_MIN_MS = 5 * 60_000;
const HOUR_MS = 60 * 60_000;
const FINE_WINDOW_MS = HOUR_MS;
const HORIZON_MS = 48 * HOUR_MS;

/** anchor（ポップオーバーを開いた時点の時刻）を基準に、直近60分以上は5分刻み・それ以降は
 * 48時間先まで正時（0分）刻みの目盛りを生成する。5分刻み区間の長さは60〜115分の間で
 * 変動する——5分刻みの終端をanchor+60分固定にはせず、そこから見て最初の正時に揃える
 * ことで、5分刻み→1時間刻みの切り替わり目が必ず正時になり、重複・欠落が生じない
 * （anchor+60分がちょうど正時なら60分ちょうどで切り替わる）。 */
export function buildDepartureTimeline(anchor: Date): Date[] {
  const fineStartMs = Math.floor(anchor.getTime() / FIVE_MIN_MS) * FIVE_MIN_MS;
  const transitionMs = Math.ceil((fineStartMs + FINE_WINDOW_MS) / HOUR_MS) * HOUR_MS;
  const times: Date[] = [];
  for (let t = fineStartMs; t <= transitionMs; t += FIVE_MIN_MS) {
    times.push(new Date(t));
  }
  const horizonMs = anchor.getTime() + HORIZON_MS;
  for (let t = transitionMs + HOUR_MS; t <= horizonMs; t += HOUR_MS) {
    times.push(new Date(t));
  }
  return times;
}

/** DynamicLayerTimeSlider向けのラベル列。ラベルの書式は気象レイヤーの共有タイムラインと
 * 同じものを使う（`lib/time.ts`）。正時の目盛りには、日本時間の偶数時だけ時刻を書く。 */
export function buildDepartureFrames(timeline: readonly Date[]): DynamicLayerTimeSliderFrame[] {
  return timeline.map((time) => {
    const { hour, minute } = jstParts(time);
    const isHour = minute === 0;
    return {
      label: formatJstDateTime(time),
      hourMark: isHour,
      tickLabel: isHour ? (hour % 2 === 0 ? formatJstHourMinute(time) : undefined) : formatJstMinute(time),
    };
  });
}
