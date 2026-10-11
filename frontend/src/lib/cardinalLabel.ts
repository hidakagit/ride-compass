/** 角度を方位の呼び名へ。**画面部品ではなくここに置く**（描くものの持ち物ではない）。
 *
 * 呼び名の並びは源泉が配り（`domain/geo.py: COMPASS_LABELS`）、区分の幅はその数から決まる。
 * 丸め方だけが画面側にあり、区分の境界を含む角度でbackendと同じ呼び名になることは、backendが出す
 * 表（生成物`geo-expectations.json`）をテストが通して確かめる。
 */
import { mapDisplay } from "@/types/generated/mapDisplay";

const CARDINAL_LABELS = mapDisplay.compassLabels;
const SECTOR_DEG = 360 / CARDINAL_LABELS.length;

/** 角度を0以上360未満へ畳む。 */
export function normalizeDeg(deg: number): number {
  return ((deg % 360) + 360) % 360;
}

export function cardinalLabel(bearingDeg: number): string {
  const index = Math.round(normalizeDeg(bearingDeg) / SECTOR_DEG) % CARDINAL_LABELS.length;
  return CARDINAL_LABELS[index];
}
