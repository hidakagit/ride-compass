/** 凡例で隠した行の保存先の読み書き。
 *
 * 保存先は画面に1つだけで、レンズ・地図上チップの▶パネル・「絞り込みをすべて解除」の
 * どこから操作しても同じ場所を読み書きする。鍵は凡例を出す側の宣言が決める。
 */
import type { HiddenLegendKeys } from "./mapLook";

const NONE: readonly string[] = [];

export function hiddenKeysOf(store: HiddenLegendKeys, axisId: string): readonly string[] {
  return store[axisId] ?? NONE;
}

/** 空にした軸も空の並びとして残す——消すと、最初に隠す行を持つ軸が次の訪問でまた隠れる。 */
export function withHiddenKeys(store: HiddenLegendKeys, axisId: string, keys: readonly string[]): HiddenLegendKeys {
  return { ...store, [axisId]: keys };
}

export function toggleHiddenKey(store: HiddenLegendKeys, axisId: string, key: string): HiddenLegendKeys {
  const current = hiddenKeysOf(store, axisId);
  return withHiddenKeys(store, axisId, current.includes(key) ? current.filter((k) => k !== key) : [...current, key]);
}

/** 凡例の全段をまとめて切り替えたあとの隠す段。1つのチェックで両方向を兼ねる（全部表示中なら全部隠し、1つでも
 * 隠れていれば全部出す）。 */
export function hiddenAfterToggleAll(legend: readonly { key: string }[], hidden: readonly string[]): string[] {
  return hidden.length === 0 ? legend.map((entry) => entry.key) : [];
}

/** いま描いている凡例に実在する鍵だけ。保存先は段の綴りや段数が変わる前の値も持ちうるため、
 * 保存値の長さをそのまま使うと、隠れた段が無いのに絞り込み中に見える。 */
export function presentHiddenKeys(legend: readonly { key: string }[], hidden: readonly string[]): readonly string[] {
  return hidden.filter((key) => legend.some((entry) => entry.key === key));
}

/** 保存値を、最初に隠す行（`initial`）の上に重ねる。保存値に無い軸（触ったことの無い軸・あとから足した層）は最初に
 * 隠す行のままにする。文字列の配列でない鍵は捨てる（読めない保存値の例外は`useStoredState`が既定値へ倒す）。 */
export function deserializeHiddenLegendKeys(raw: string, initial: HiddenLegendKeys): HiddenLegendKeys | null {
  const parsed: unknown = JSON.parse(raw);
  if (parsed === null || typeof parsed !== "object") return null;
  const stored = Object.entries(parsed).filter(
    (entry): entry is [string, string[]] => Array.isArray(entry[1]) && entry[1].every((key) => typeof key === "string"),
  );
  return { ...initial, ...Object.fromEntries(stored) };
}
