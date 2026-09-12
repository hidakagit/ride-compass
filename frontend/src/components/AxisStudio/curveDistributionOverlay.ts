// 曲線エディタの背景へ実データの分布を重ねるための純関数（DOM非依存）。
//
// 折れ点だけを見ても「その形が実際の道路のどこに効いているか」は分からない。値が集中する
// 帯の外側で曲線を動かしても結果は変わらず、逆に集中する帯の中で急にすると大きく変わる。
//
// 曲線エディタの横軸は**折れ点を通す前の生値**（Σ 材料値×重み）で、backendが返す
// `ValueDistribution`の階級・分位と同じ量。したがって階級をそのまま横軸へ重ねられる。

import type { ValueDistribution } from "./scoreDistribution";

export interface DistributionBar {
  /** 横軸上の区間（生値）。表示範囲でクリップ済み。 */
  from: number;
  to: number;
  /** この階級が占める延長の割合（0〜1）。クリップした分は幅に比例して按分する。 */
  share: number;
}

export interface QuantileMarker {
  label: string;
  value: number;
}

export interface OffRangeShare {
  /** 表示範囲より小さい側／大きい側にある延長の割合（0〜1）。 */
  below: number;
  above: number;
}

/** 背景へ描く分位線。全6分位を出すと線だらけになるため、外れ・中央・外れの3本に絞る。 */
const VISIBLE_QUANTILES = ["p10", "p50", "p90"] as const;

/** 「範囲外がある」と注意を促す下限。丸め誤差や極端な外れ値1本で毎回出しても意味が無い。 */
export const OFF_RANGE_NOTICE_THRESHOLD = 0.02;

function overlap(from: number, to: number, min: number, max: number): number {
  return Math.max(0, Math.min(to, max) - Math.max(from, min));
}

/**
 * 表示範囲へ収まる部分だけの階級を返す。
 *
 * 階級が範囲をまたぐ場合、その階級の延長は**幅に比例して按分**する（階級内は一様と
 * みなす）。またがる階級を丸ごと入れる／落とすと、範囲の端で割合が跳ねる。
 */
export function visibleBars(
  distribution: ValueDistribution | null,
  xMin: number,
  xMax: number,
): DistributionBar[] {
  if (!distribution || xMax <= xMin) return [];
  const bars: DistributionBar[] = [];
  for (const [from, to, share] of distribution.bins) {
    const width = to - from;
    // 幅0の階級（値が1点に集中）は按分できない。`overlap`も0を返すため、範囲内か
    // どうかだけで判定してそのまま載せる。
    if (width <= 0) {
      if (from >= xMin && from <= xMax) bars.push({ from, to: from, share });
      continue;
    }
    const inside = overlap(from, to, xMin, xMax);
    if (inside <= 0) continue;
    bars.push({ from: Math.max(from, xMin), to: Math.min(to, xMax), share: share * (inside / width) });
  }
  return bars;
}

/**
 * 表示範囲の外にある延長の割合。
 *
 * 範囲外を黙って捨てると「分布は全部見えている」と読めてしまい、**折れ点が実データの
 * 範囲と合っていないこと自体**（値の大半が曲線の外側にある状態）が画面から消える。
 * それはこの重ね描きが一番伝えたいことなので、割合として残す。
 */
export function offRangeShare(
  distribution: ValueDistribution | null,
  xMin: number,
  xMax: number,
): OffRangeShare {
  if (!distribution) return { below: 0, above: 0 };
  let below = 0;
  let above = 0;
  // 表示範囲が潰れている（折れ点が1点に集中した等）ときは、範囲内が無いので全量が範囲外。
  // `visibleBars`と同じ条件でここでも分岐する——片方だけ分岐すると、
  // `overlap(-∞, xMin)`と`overlap(xMax, ∞)`が同じ区間を二重に数え、割合の合計が1を超える。
  const degenerate = xMax <= xMin;
  for (const [from, to, share] of distribution.bins) {
    const width = to - from;
    if (degenerate || width <= 0) {
      if (from < xMin) below += share;
      else if (from > xMax) above += share;
      else if (degenerate) above += share;
      continue;
    }
    below += share * (overlap(from, to, -Infinity, xMin) / width);
    above += share * (overlap(from, to, xMax, Infinity) / width);
  }
  return { below, above };
}

/** 表示範囲に入る分位だけを、横軸へ引く順に返す。 */
export function quantileMarkers(
  distribution: ValueDistribution | null,
  xMin: number,
  xMax: number,
): QuantileMarker[] {
  if (!distribution) return [];
  return VISIBLE_QUANTILES.flatMap((label) => {
    const value = distribution.quantiles[label];
    if (value === undefined || value < xMin || value > xMax) return [];
    return [{ label, value }];
  });
}

/** 棒の高さを正規化するための最大割合（0除算を避ける）。 */
export function maxBarShare(bars: readonly DistributionBar[]): number {
  return Math.max(...bars.map((b) => b.share), Number.EPSILON);
}
