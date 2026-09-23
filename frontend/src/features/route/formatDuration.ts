/** 秒を「1時間42分」「38分」の形にする。1分未満は「1分未満」。 */
export function formatDurationShort(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const totalMinutes = Math.round(seconds / 60);
  if (totalMinutes < 1) return "1分未満";
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours}時間${minutes}分` : `${minutes}分`;
}
