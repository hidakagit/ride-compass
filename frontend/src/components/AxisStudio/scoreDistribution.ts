// 折れ点を当てはめて得点帯ごとの延長割合を求める純関数（DOM非依存）。
//
// backendは折れ点を通す前の生値のヒストグラムだけを返し、折れ点の当てはめはここで行う
// （折れ点を1つ動かすたびに通信すると編集の手応えが失われるうえ、折れ点は区分線形の
// 写像でしかなく、生値のヒストグラムがあればクライアントで正確に求まる）。

/** backendが返す生値の分布（`services/axisPreviewApi.ts`のレスポンスと同じ形）。 */
export interface ValueDistribution {
  sample_ways: number;
  total_km: number;
  quantiles: Record<string, number>;
  /** [階級の下限, 上限, その階級が占める延長の割合] */
  bins: [number, number, number][];
  zero_share: number;
}

export interface ScoreBand {
  label: string;
  /** この帯が占める延長の割合（0〜1） */
  share: number;
}

/** 得点帯の区切り。0点と100点は「張り付き」を見たいので単独の帯として分ける。 */
const BAND_EDGES: readonly { label: string; min: number; max: number }[] = [
  { label: "0点", min: 0, max: 0 },
  { label: "1-25", min: 0, max: 25 },
  { label: "26-50", min: 25, max: 50 },
  { label: "51-75", min: 50, max: 75 },
  { label: "76-99", min: 75, max: 100 },
  { label: "100点", min: 100, max: 100 },
];

/** 区分線形の折れ点で値を得点へ写す（backend `BreakpointLinearShape`と同じ規則）。 */
export function scoreForValue(value: number, breakpoints: readonly [number, number][]): number {
  if (breakpoints.length === 0) return 0;
  const sorted = [...breakpoints].sort((a, b) => a[0] - b[0]);
  if (value <= sorted[0][0]) return sorted[0][1];
  for (let i = 0; i < sorted.length - 1; i += 1) {
    const [x0, y0] = sorted[i];
    const [x1, y1] = sorted[i + 1];
    if (value <= x1) {
      if (x1 === x0) return y1;
      return y0 + ((value - x0) / (x1 - x0)) * (y1 - y0);
    }
  }
  return sorted[sorted.length - 1][1];
}

/** 生値の分布へ折れ点を当てはめ、得点帯ごとの延長割合を返す。 */
export function scoreBands(
  distribution: ValueDistribution | null,
  breakpoints: readonly [number, number][],
): ScoreBand[] {
  const bands = BAND_EDGES.map((edge) => ({ label: edge.label, share: 0 }));
  if (!distribution || distribution.bins.length === 0) return bands;
  for (const [lower, upper, share] of distribution.bins) {
    // 階級の代表値は中央。階級幅は分布全体を等分したもので、この粒度より細かい
    // 折れ点の差は画面上の意味を持たない。
    const score = scoreForValue((lower + upper) / 2, breakpoints);
    let index: number;
    if (score <= 0) index = 0;
    else if (score >= 100) index = BAND_EDGES.length - 1;
    else if (score <= 25) index = 1;
    else if (score <= 50) index = 2;
    else if (score <= 75) index = 3;
    else index = 4;
    bands[index].share += share;
  }
  return bands;
}

/** 折れ点が実データに対して極端すぎないかの警告。無ければ空配列。 */
export function distributionWarnings(bands: readonly ScoreBand[]): string[] {
  const warnings: string[] = [];
  const full = bands.find((b) => b.label === "100点")?.share ?? 0;
  const zero = bands.find((b) => b.label === "0点")?.share ?? 0;
  if (full >= 0.5) {
    warnings.push(
      `延長の${Math.round(full * 100)}%が満点に張り付きます。上限を高くしないと道の差が出ません。`,
    );
  }
  if (zero >= 0.9) {
    warnings.push(
      `延長の${Math.round(zero * 100)}%が0点です。下限を下げないとほとんどの道が同じ評価になります。`,
    );
  }
  return warnings;
}
