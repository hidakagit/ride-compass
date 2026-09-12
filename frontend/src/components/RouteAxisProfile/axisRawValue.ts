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
 * 距離あたりの単位のときだけ実数（約N回）を添える——「%」のような量は距離を掛けても
 * 意味を持たないため。
 */
export function formatAxisRawValue(
  rawValue: number | undefined,
  unit: string | null | undefined,
  distanceKm: number | null | undefined,
): string | null {
  if (rawValue == null || !unit) return null;
  const perDistance = totalUnitFor(unit);
  const head = `${formatNumber(rawValue)}${unit}`;
  if (perDistance === null || distanceKm == null || distanceKm <= 0) return head;
  const total = rawValue * distanceKm;
  // 1未満まで細かく出しても行動は変わらないため、四捨五入して「約」を付ける。
  if (total < 0.5) return head;
  return `${head}・約${Math.round(total)}${perDistance}`;
}

// 生値のスケールは軸ごとに違う（勾配は%で0〜15程度、事故密度は件/(km・年)で0〜0.5）。
// 固定の小数桁だと桁の小さい軸で「0.00」に潰れ、値の無い道と区別できなくなる。
// 大きい値は桁を落とし、小さい値は有効数字2桁を残す。
function formatNumber(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude >= 10) return value.toFixed(0);
  if (magnitude >= 1) return value.toFixed(1);
  if (magnitude === 0) return "0";
  // 有効数字2桁（末尾の0は落とす）。0.08 → "0.08"、0.041 → "0.041"、0.0041 → "0.0041"
  return String(Number(value.toPrecision(2)));
}

/**
 * 内訳1件を人が読める文へ整える（例:「街灯あり 68%」「制限速度 42km/h」）。出す先は
 * 軸の説明ポップオーバーで、パネルの行には出さない（設計原則「数値は3層で見せる」）。
 *
 * 表記は材料の型から決まり、軸ごとの対応表を持たない。真偽値材料の値は0/1で運ばれる
 * （backendの`route_facing_material_ids`）ため、距離加重平均がそのまま該当区間の
 * 延長割合になる。値が来ない材料（categorical材料は数値列に載らない）はnullを返し、
 * 呼び出し側が飛ばす。
 */
export function formatMaterialBreakdown(
  entry: { label: string; dtype: string; unit: string },
  value: number | undefined,
): string | null {
  if (value == null || !Number.isFinite(value)) return null;
  if (entry.dtype === "boolean") return `${entry.label} ${Math.round(value * 100)}%`;
  if (entry.dtype !== "numeric") return null;
  return `${entry.label} ${formatNumber(value)}${entry.unit}`;
}

/**
 * categorical材料の内訳1件（例:「住宅街の道 62%」）。
 *
 * 出すのは**最も延長の長い値**1つだけ。backendが割合の降順で返すので先頭を取る
 * （フロントは並べ替えを持たない）。「幹線道路が◯%」のように複数の値をまとめた形には
 * しない——どの値を幹線とみなすかという判断表をフロントが持つことになり、軸を1本足すと
 * 表の更新が要る状態に戻るため。ラベルはbackendが返す対訳（`valueLabels`）を引き、
 * 未登録の値はタグ生値をそのまま出す（新しいOSMタグ値が現れても壊れない）。
 */
export function formatCategoryBreakdown(
  entry: { label: string; valueLabels?: Readonly<Record<string, string>> },
  shares: Readonly<Record<string, number>> | undefined,
): string | null {
  const top = Object.entries(shares ?? {})[0];
  if (top === undefined) return null;
  const [value, share] = top;
  if (!Number.isFinite(share)) return null;
  return `${entry.valueLabels?.[value] ?? value} ${Math.round(share * 100)}%`;
}
