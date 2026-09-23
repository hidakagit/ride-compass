/** 角度を8方位の呼び名へ。**画面部品ではなくここに置く**（描くものの持ち物ではない）。
 *
 * 呼び名の並びは源泉が配る（`domain/geo.py: COMPASS_LABELS`）。丸め方だけが画面側にあり、
 * **backendと同じhalf-up**でなければ境界（22.5°・67.5°…）でラベルが食い違う。
 */
import { mapDisplay } from "@/types/generated/mapDisplay";

const CARDINAL_LABELS = mapDisplay.compassLabels;

export function cardinalLabel(bearingDeg: number): string {
  const normalized = ((bearingDeg % 360) + 360) % 360;
  const index = Math.round(normalized / 45) % 8;
  return CARDINAL_LABELS[index];
}
