import type { RoutePreferenceWeights } from "@/types/route";

// 重み配分の調整量の刻みと、1軸が取りうる重みの範囲。下限は0ではない——0まで下げると
// その軸は「チェックOFF」（weight>0が有効の判定基準）に化けるため、配分の調整操作で
// 軸の有効/無効を兼ねさせない。
export const WEIGHT_STEP = 0.01;
export const MIN_AXIS_WEIGHT = WEIGHT_STEP;
export const MAX_AXIS_WEIGHT = 0.6;

export function roundToStep(value: number): number {
  return Number(value.toFixed(2));
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function totalWeight(weights: RoutePreferenceWeights): number {
  return Object.values(weights).reduce((sum, w) => sum + (w > 0 ? w : 0), 0);
}

/** 帯グラフの境界（隣り合う2軸の重み合計を変えずに一方から他方へ移す）ドラッグで、
 * 生の移動量（重み単位）を両軸の[MIN_AXIS_WEIGHT, MAX_AXIS_WEIGHT]範囲内へ収まるよう
 * クランプし、WEIGHT_STEP単位へ丸めた最終的な2軸ぶんの新しい重みを返す。
 * 合計（weightA+weightB）は常に変わらない——丸め後もdeltaを共有するため浮動小数点誤差で
 * ずれない。 */
export function clampBoundaryDrag(
  weightA: number,
  weightB: number,
  rawDelta: number
): { weightA: number; weightB: number } {
  const lowerBound = Math.max(MIN_AXIS_WEIGHT - weightA, weightB - MAX_AXIS_WEIGHT);
  const upperBound = Math.min(MAX_AXIS_WEIGHT - weightA, weightB - MIN_AXIS_WEIGHT);
  const clamped = clamp(rawDelta, lowerBound, upperBound);
  const steppedDelta = Math.round(clamped / WEIGHT_STEP) * WEIGHT_STEP;
  return {
    weightA: roundToStep(weightA + steppedDelta),
    weightB: roundToStep(weightB - steppedDelta),
  };
}
