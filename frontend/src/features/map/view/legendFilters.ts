/** 凡例で隠した行の保存先（`hiddenLegendKeysByMode`）と、そこから地図の各家族へ渡す形を導く。
 *
 * 保存先は画面に1つだけで、レンズ（`LensControl`）・地図上チップの▶パネル・「絞り込みを
 * すべて解除する」のどこから操作しても同じ場所を読み書きする。鍵は凡例を出す側の宣言が決める
 * （道路の線は一次属性id、点は`scene/legends.ts`の軸id、評価軸は軸id、災害の要素トグルは
 * チップid）。
 */
import type { RampAxis, DedicatedWayValueAxis } from "@/components/Map/axisLayers";
import type { LegendEntry } from "@/components/Map/legendFilter";
import { pointLegendAxes, roadLegendAxes } from "@/features/map/scene/legends";

/** 鍵（凡例の保存先id）→ 隠した行の鍵。 */
export type HiddenLegendKeys = Readonly<Record<string, readonly string[]>>;

export const NO_HIDDEN_KEYS: readonly string[] = [];

export const EMPTY_HIDDEN_LEGEND_KEYS: HiddenLegendKeys = {};

export function hiddenKeysOf(store: HiddenLegendKeys, axisId: string): readonly string[] {
  return store[axisId] ?? NO_HIDDEN_KEYS;
}

export function toggleHiddenKey(store: HiddenLegendKeys, axisId: string, key: string): HiddenLegendKeys {
  const current = hiddenKeysOf(store, axisId);
  const next = current.includes(key) ? current.filter((k) => k !== key) : [...current, key];
  return withHiddenKeys(store, axisId, next);
}

/** 空にした鍵は保存先から消す——空配列を残すと、使われなくなった鍵が保存値に溜まり続ける。 */
export function withHiddenKeys(store: HiddenLegendKeys, axisId: string, keys: readonly string[]): HiddenLegendKeys {
  const next: Record<string, readonly string[]> = { ...store };
  if (keys.length === 0) delete next[axisId];
  else next[axisId] = [...keys];
  return next;
}

/** いま描いている凡例に実在する鍵だけ。保存先は段の綴りや段数が変わる前の値も持ちうるため、
 * 長さをそのまま「絞り込み中か」に使うと、隠れた段が無いのに絞り込み中と見える。 */
export function presentHiddenKeys(legend: readonly LegendEntry[], hidden: readonly string[]): readonly string[] {
  if (hidden.length === 0) return NO_HIDDEN_KEYS;
  const present = hidden.filter((key) => legend.some((entry) => entry.key === key));
  return present.length === hidden.length ? hidden : present;
}

/** 地図（`MapView`）へ渡す、家族ごとの隠した行。**鍵の母集団は凡例を出す宣言そのもの**
 * （道路の線・点は`scene/legends.ts`、評価軸は軸カタログ）で、ここで鍵を並べない。 */
export function mapHiddenKeysFrom(
  store: HiddenLegendKeys,
  rampAxes: readonly RampAxis[],
  dedicatedAxes: readonly DedicatedWayValueAxis[],
): {
  roadHiddenKeysByMode: Record<string, readonly string[]>;
  staticLegendHiddenKeysByAxis: Record<string, readonly string[]>;
  dedicatedWayValueHiddenBands: ReadonlyMap<string, readonly string[]>;
} {
  const pick = (axisIds: readonly string[]) =>
    Object.fromEntries(axisIds.map((axisId) => [axisId, hiddenKeysOf(store, axisId)]));
  return {
    roadHiddenKeysByMode: pick(roadLegendAxes().map((axis) => axis.axisId)),
    staticLegendHiddenKeysByAxis: pick([
      ...pointLegendAxes().map((axis) => axis.axisId),
      ...rampAxes.map((axis) => axis.axisId),
    ]),
    dedicatedWayValueHiddenBands: new Map(dedicatedAxes.map((axis) => [axis.axisId, hiddenKeysOf(store, axis.axisId)])),
  };
}

export function serializeHiddenLegendKeys(store: HiddenLegendKeys): string {
  return JSON.stringify(store);
}

/** 形の合わない値は読まない。文字列でない要素は落とし、配列でない鍵は捨てる。 */
export function deserializeHiddenLegendKeys(raw: string): HiddenLegendKeys | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const store: Record<string, readonly string[]> = {};
  for (const [axisId, keys] of Object.entries(parsed)) {
    if (!Array.isArray(keys)) continue;
    const strings = keys.filter((key): key is string => typeof key === "string");
    if (strings.length > 0) store[axisId] = strings;
  }
  return store;
}
