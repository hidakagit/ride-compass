// 軸の生値（折れ点を通す前）を、人が読める文（例:「0.8回/km・約26回」）へ整える純関数。
//
// 得点（0〜100）は目盛りの引き方に依存する相対評価のため、軸単体では経路の良し悪しを
// 判断できない。生値を単位付きで添えると、他の軸を見ずに判断できる。
// 単位が定まらない軸（合成軸・真偽値の軸）はbackendが`raw_value_unit`にnullを返すため、
// ここへは来ない。

/** 単位が「◯◯/km」なら、距離を掛けて経路全体の実数にできる。 */
export function totalUnitFor(unit: string): string | null {
  const suffix = "/km";
  return unit.endsWith(suffix) ? unit.slice(0, -suffix.length) : null;
}

/**
 * 表示文を組み立てる。`rawValue`は距離加重平均の生値、`distanceKm`は経路の走行距離。
 *
 * 距離あたりの単位（`◯◯/km`）なら**経路全体の実数だけ**を出す（`約26回`）。密度そのものは
 * 得点を決めている当の値で、隣に得点が並んでいる以上は繰り返しになる——利用者が読みたいのは
 * 「結局何回止まるのか」であり、一覧の列幅もその1つぶんで済む。距離を掛けられない単位
 * （`%`等）は生値をそのまま単位付きで出す。
 */
export function formatAxisRawValue(
  rawValue: number | undefined,
  unit: string | null | undefined,
  distanceKm: number | null | undefined,
): string | null {
  if (rawValue == null || !unit) return null;
  const perDistance = totalUnitFor(unit);
  if (perDistance === null || distanceKm == null || distanceKm <= 0) {
    return `${formatNumber(rawValue)}${unit}`;
  }
  const total = rawValue * distanceKm;
  // 四捨五入して0になる量は「0回」と言い切らず密度のまま出す（丸めで消したことを隠さない）。
  if (total < 0.5) return `${formatNumber(rawValue)}${unit}`;
  return `約${Math.round(total)}${perDistance}`;
}

function formatNumber(value: number): string {
  if (Math.abs(value) >= 10) return value.toFixed(0);
  if (Math.abs(value) >= 1) return value.toFixed(1);
  return value.toFixed(2);
}
