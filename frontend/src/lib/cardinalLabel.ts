/** 角度を方位の呼び名へ。**画面部品ではなくここに置く**（描くものの持ち物ではない）。
 *
 * 呼び名の並びは源泉が配り（`domain/geo.py: COMPASS_LABELS`）、区分の幅はその数から決まる。
 * 丸め方だけが画面側にあり、**backendと同じhalf-up**でなければ区分の境界でラベルが食い違う。
 */
import { mapDisplay } from "@/types/generated/mapDisplay";

const CARDINAL_LABELS = mapDisplay.compassLabels;
const SECTOR_DEG = 360 / CARDINAL_LABELS.length;

export function cardinalLabel(bearingDeg: number): string {
  const normalized = ((bearingDeg % 360) + 360) % 360;
  const index = Math.round(normalized / SECTOR_DEG) % CARDINAL_LABELS.length;
  return CARDINAL_LABELS[index];
}
