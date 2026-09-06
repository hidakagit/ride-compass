// 出発時刻ピッカー（RideConditionBar）のドラッグタイムライン用の目盛り生成。気象レイヤーの
// 実フレーム（フェッチ結果）には依存しない——出発時刻はレイヤーが1つもONでなくても設定できる
// 必要があるため（dynamicWeather.ts: mergeFrameTimesはON中のレイヤーのフレームしか統合しない）。
// 粒度は気象ナウキャスト・延長予報と同じ「直近60分は5分刻み、以降48時間先までは1時間刻み」に
// 揃え、選んだ出発時刻が気象レイヤーのフレームへ素直に対応するようにする。
import {
  formatDynamicFrameHourMinute,
  formatDynamicFrameMinuteOnly,
  formatDynamicFrameTime,
} from "@/components/Map/dynamicWeather";
import type { DynamicLayerTimeSliderFrame } from "@/components/DynamicLayerTimeSlider/DynamicLayerTimeSlider";

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

/** DynamicLayerTimeSlider向けのラベル列。正時判定・ラベル間引きの規則は、
 * useDynamicWeatherLayers.tsが気象レイヤーの共有タイムライン向けに使っているものと同じ
 * （formatDynamicFrameTime/dynamicWeather.test.ts参照）。 */
export function buildDepartureFrames(timeline: readonly Date[]): DynamicLayerTimeSliderFrame[] {
  return timeline.map((time) => {
    const isHour = time.getUTCMinutes() === 0;
    return {
      label: formatDynamicFrameTime(time),
      hourMark: isHour,
      tickLabel: isHour
        ? time.getUTCHours() % 2 === 0
          ? formatDynamicFrameHourMinute(time)
          : undefined
        : formatDynamicFrameMinuteOnly(time),
    };
  });
}
