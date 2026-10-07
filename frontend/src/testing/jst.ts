/** 日本時間の壁時計の表記（`"2026-10-07T09:00"`）が指す時刻。 */
export const jst = (text: string) => new Date(`${text}+09:00`);
