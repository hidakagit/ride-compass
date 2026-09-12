import type { RoutePreferenceWeights } from "@/types/route";

// 重み配分の調整量の刻みと、1軸が取りうる重みの範囲。下限は0ではない——0まで下げると
// その軸は「チェックOFF」（weight>0が有効の判定基準）に化けるため、配分の調整操作で
// 軸の有効/無効を兼ねさせない。
export const WEIGHT_STEP = 0.01;
export const MIN_AXIS_WEIGHT = WEIGHT_STEP;
export const MAX_AXIS_WEIGHT = 0.6;

/** ±ボタン1回で動かす割合（%ポイント）。 */
export const SHARE_STEP_PCT = 1;

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

/** 1軸の取り分（%）をdeltaPctだけ動かし、その増減を**他の有効な軸すべてから今の比率で
 * 按分して**埋め合わせた新しい重みを返す。有効な軸の重みの合計は変えないため、画面に
 * 出る他の軸の%は「増やした軸が取ったぶんだけ」一斉に下がる（どこから来たかが読める）。
 * 動かせない場合（有効な軸が1つしかない・全ての相手が上下限に張り付いている）はnullを返す。
 *
 * 配分はWEIGHT_STEP刻みの整数個を出し入れする形で行う（比率どおりの実数を各軸で丸めると、
 * 軸が多いときに全軸ぶんの端数が消えて「押しても何も動かない」になる）。1ステップ未満の
 * 要求でも必ず1ステップは動かす。刻みが1つしか無いときは比率どおりに割れないため、
 * 最大剰余法の結果として配分の大きい軸から先に払う。 */
export function adjustAxisShare(
  weights: RoutePreferenceWeights,
  axisId: string,
  deltaPct: number
): RoutePreferenceWeights | null {
  const current = weights[axisId] ?? 0;
  if (current <= 0 || deltaPct === 0) return null;
  const others = Object.entries(weights)
    .filter(([id, w]) => id !== axisId && w > 0)
    .map(([id, w]) => ({ id, weight: w }));
  if (others.length === 0) return null;

  const total = totalWeight(weights);
  const othersTotal = total - current;
  if (othersTotal <= 0) return null;

  // 動かしたいステップ数（最低1ステップ）。自分自身の上下限でも頭打ちにする。
  const taking = deltaPct > 0;
  const requested = Math.max(1, Math.round((Math.abs(deltaPct) / 100) * total / WEIGHT_STEP));
  const selfCapacity = Math.round(
    ((taking ? MAX_AXIS_WEIGHT - current : current - MIN_AXIS_WEIGHT) + Number.EPSILON) / WEIGHT_STEP
  );
  let moving = Math.min(requested, Math.max(0, selfCapacity));
  if (moving === 0) return null;

  // 相手側の余力（ステップ数）。取りにいくときは下限まで、渡すときは上限まで。
  const capacity = others.map(({ weight }) =>
    Math.max(
      0,
      Math.round(((taking ? weight - MIN_AXIS_WEIGHT : MAX_AXIS_WEIGHT - weight) + Number.EPSILON) / WEIGHT_STEP)
    )
  );
  const capacityTotal = capacity.reduce((sum, c) => sum + c, 0);
  moving = Math.min(moving, capacityTotal);
  if (moving === 0) return null;

  // 比率どおりの理想値を整数部で配り、余りを端数の大きい順に1ステップずつ足す（最大剰余法）。
  const ideal = others.map(({ weight }) => (moving * weight) / othersTotal);
  const allocated = ideal.map((value, i) => Math.min(Math.floor(value), capacity[i]));
  let remaining = moving - allocated.reduce((sum, a) => sum + a, 0);
  const order = ideal
    .map((value, i) => ({ i, fraction: value - Math.floor(value) }))
    .sort((a, b) => b.fraction - a.fraction);
  while (remaining > 0) {
    const before = remaining;
    for (const { i } of order) {
      if (remaining === 0) break;
      if (allocated[i] < capacity[i]) {
        allocated[i] += 1;
        remaining -= 1;
      }
    }
    if (remaining === before) break;
  }

  const next: RoutePreferenceWeights = { ...weights };
  let movedSteps = 0;
  others.forEach(({ id, weight }, i) => {
    const delta = taking ? -allocated[i] : allocated[i];
    movedSteps += allocated[i];
    next[id] = roundToStep(weight + delta * WEIGHT_STEP);
  });
  if (movedSteps === 0) return null;
  next[axisId] = roundToStep(current + (taking ? movedSteps : -movedSteps) * WEIGHT_STEP);
  return next;
}
