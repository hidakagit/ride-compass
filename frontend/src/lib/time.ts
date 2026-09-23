// 画面に出す時刻は、見る人の端末の時刻帯によらず日本時間で表す——道路データも経路も日本の中で、
// backendも日本時間で扱う（`domain/time_zone.py`）。日本に夏時間は無いので、協定世界時から
// 9時間ずらすだけで日本時間の暦と時刻が求まる。

const JST_OFFSET_MS = 9 * 60 * 60 * 1000;

interface JstParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

/** その時点の、日本時間の暦と時刻。 */
export function jstParts(time: Date): JstParts {
  const shifted = new Date(time.getTime() + JST_OFFSET_MS);
  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
    hour: shifted.getUTCHours(),
    minute: shifted.getUTCMinutes(),
  };
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/** 「09:05」 */
export function formatJstHourMinute(time: Date): string {
  const { hour, minute } = jstParts(time);
  return `${pad2(hour)}:${pad2(minute)}`;
}

/** 「8/20 09:05」 */
export function formatJstDateTime(time: Date): string {
  const { month, day } = jstParts(time);
  return `${month}/${day} ${formatJstHourMinute(time)}`;
}

/** 「05」（分だけ） */
export function formatJstMinute(time: Date): string {
  return pad2(jstParts(time).minute);
}

/** 2つの時点が日本時間で同じ日か。 */
export function isSameJstDay(a: Date, b: Date): boolean {
  const x = jstParts(a);
  const y = jstParts(b);
  return x.year === y.year && x.month === y.month && x.day === y.day;
}

/** `input[type=datetime-local]`の値（時刻帯を持たない`YYYY-MM-DDTHH:mm`）を、日本時間として書く。 */
export function toJstDatetimeLocalValue(time: Date): string {
  const { year, month, day, hour, minute } = jstParts(time);
  return `${year}-${pad2(month)}-${pad2(day)}T${pad2(hour)}:${pad2(minute)}`;
}

/** `input[type=datetime-local]`の値を、日本時間として読む（ブラウザは端末の時刻帯で読む）。 */
export function fromJstDatetimeLocalValue(value: string): Date {
  return new Date(`${value}+09:00`);
}

/** timesの中で対象時刻に最も近いindex。空配列なら0（スライダーのつまみ位置導出用。
 * 範囲外でも端へクランプする——スライダーの見た目としては端が正しい位置のため）。 */
export function nearestTimeIndex(times: readonly Date[], target: Date): number {
  if (times.length === 0) return 0;
  const targetMs = target.getTime();
  let bestIndex = 0;
  let bestDiffMs = Infinity;
  for (let i = 0; i < times.length; i++) {
    const diffMs = Math.abs(times[i].getTime() - targetMs);
    if (diffMs < bestDiffMs) {
      bestDiffMs = diffMs;
      bestIndex = i;
    }
  }
  return bestIndex;
}
