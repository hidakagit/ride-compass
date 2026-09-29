/** 秒を「102分」「38分」の形にする（1時間を超えても分で書く）。1分未満は「1分未満」。 */
export function formatDurationShort(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const totalMinutes = Math.round(seconds / 60);
  if (totalMinutes < 1) return "1分未満";
  return `${totalMinutes}分`;
}
