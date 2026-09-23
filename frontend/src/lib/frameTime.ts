/** 共有スライダーの表示用時刻ラベル（JST）。タイムラインは約48時間先まで日付をまたぐため
 * 常に日付を含める（レイヤーごとのラベル形式差を表示層へ持ち込まない）。WeatherPanel
 * の左端インジケータ上に1行で出す「正確な日時」用。 */
export function formatDynamicFrameTime(time: Date): string {
  return `${formatDynamicFrameDate(time)} ${formatDynamicFrameHourMinute(time)}`;
}

/** 日付のみ（JST、月/日）。formatDynamicFrameTimeが内部で使う。 */
function formatDynamicFrameDate(time: Date): string {
  return time.toLocaleDateString("ja-JP", { month: "numeric", day: "numeric", timeZone: "Asia/Tokyo" });
}

/** 時刻のみ（日付無し、JST、HH:mm）。WeatherPanelのルーラー目盛りラベルのうち、
 * 正時のコマ用。 */
export function formatDynamicFrameHourMinute(time: Date): string {
  return time.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo" });
}

/** 分のみ（2桁、0埋め、JST）。ルーラー目盛りラベルのうち、正時でない密な区間
 * （降水ナウキャストの5分刻み等）のコマ用。JSTはUTC+9:00ちょうどで分のずれが無いため、
 * getUTCMinutes()がそのまま
 * JSTの分と一致する（departureTimeline.tsのhourMark判定と同じ理由、実行環境の
 * ローカルタイムゾーンに左右されない）。 */
export function formatDynamicFrameMinuteOnly(time: Date): string {
  return String(time.getUTCMinutes()).padStart(2, "0");
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
