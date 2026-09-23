/** 凡例で隠した行の保存先の読み書き。
 *
 * 保存先は画面に1つだけで、レンズ・地図上チップの▶パネル・「絞り込みをすべて解除する」の
 * どこから操作しても同じ場所を読み書きする。鍵は凡例を出す側の宣言が決める。
 */
import type { HiddenLegendKeys } from "./mapLook";

const NONE: readonly string[] = [];

export function hiddenKeysOf(store: HiddenLegendKeys, axisId: string): readonly string[] {
  return store[axisId] ?? NONE;
}

export function withHiddenKeys(store: HiddenLegendKeys, axisId: string, keys: readonly string[]): HiddenLegendKeys {
  const rest = Object.fromEntries(Object.entries(store).filter(([id]) => id !== axisId));
  return keys.length === 0 ? rest : { ...rest, [axisId]: keys };
}

export function toggleHiddenKey(store: HiddenLegendKeys, axisId: string, key: string): HiddenLegendKeys {
  const current = hiddenKeysOf(store, axisId);
  return withHiddenKeys(store, axisId, current.includes(key) ? current.filter((k) => k !== key) : [...current, key]);
}

/** 文字列の配列でない鍵は捨てる（読めない保存値の例外は`useStoredState`が既定値へ倒す）。 */
export function deserializeHiddenLegendKeys(raw: string): HiddenLegendKeys | null {
  const parsed: unknown = JSON.parse(raw);
  if (parsed === null || typeof parsed !== "object") return null;
  return Object.fromEntries(
    Object.entries(parsed).filter(
      (entry): entry is [string, string[]] =>
        Array.isArray(entry[1]) && entry[1].length > 0 && entry[1].every((key) => typeof key === "string"),
    ),
  );
}
