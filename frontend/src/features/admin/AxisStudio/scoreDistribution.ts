// 生値の分布を得点帯ごとの延長割合へまとめる純関数（DOM非依存）。
//
// backendは折れ点を通す前の生値のヒストグラムを返し（重い集計のため折れ点を動かしても取り直さない）、
// 各階級の代表値の点数は別の軽い問い合わせ（`useScoresPreview`、評価と同じ計算）が返す。ここは届いた点数を
// 帯へ振り分けるだけで、点数を計算しない。

/** `GET /api/admin/material-catalog/{material_id}/distribution`の応答本体。
 *
 * backendの`ValueDistributionResponse`をそのまま使う（手書きで写すと、フィールドを足した
 * ときに片側だけ古くなる。`bins`は[階級の下限, 上限, その階級が占める延長の割合]）。 */
import type { components } from "@/types/generated/api";

export type ValueDistribution = components["schemas"]["ValueDistributionResponse"];

interface ScoreBand {
  label: string;
  /** この帯が占める延長の割合（0〜1） */
  share: number;
}

/** 0点と100点の間を分ける帯の上端（最後の帯は100点未満まで）。0点と100点は「張り付き」を
 * 見たいので単独の帯として分ける。帯の名前も判定もこの並びから作る。 */
const MIDDLE_BAND_UPPERS: readonly number[] = [25, 50, 75];

const BAND_LABELS: readonly string[] = [
  "0点",
  ...[...MIDDLE_BAND_UPPERS, 99].map((upper, i, uppers) => `${i === 0 ? 1 : uppers[i - 1] + 1}-${upper}`),
  "100点",
];

/** 「張り付き」を見る両端の位置。**ラベル文字列で引かない**——言い換えた瞬間に警告が
 * 一切出なくなる（出なくなったことにも気づけない）。 */
const ZERO_BAND_INDEX = 0;
const FULL_BAND_INDEX = BAND_LABELS.length - 1;

/** 分布の各階級の代表値（中央）。階級幅は分布全体を等分したもので、この粒度より細かい折れ点の差は画面上の
 * 意味を持たない。この値の点数を問い合わせ、`scoreBands`へ渡す。 */
export function binMidpoints(distribution: ValueDistribution | null): number[] {
  return (distribution?.bins ?? []).map(([lower, upper]) => (lower + upper) / 2);
}

/** 分布の階級ごとの点数（`binMidpoints`の順）を、得点帯ごとの延長割合へまとめる。点数が届いていない・階級と
 * 数が合わない間は、全帯を0で返す（前の折れ点の点数を今の分布へ当てない）。 */
export function scoreBands(distribution: ValueDistribution | null, binScores: readonly number[] | null): ScoreBand[] {
  const bands = BAND_LABELS.map((label) => ({ label, share: 0 }));
  if (!distribution || distribution.bins.length === 0) return bands;
  if (binScores === null || binScores.length !== distribution.bins.length) return bands;
  for (const [i, [, , share]] of distribution.bins.entries()) {
    const score = binScores[i];
    let index: number;
    if (score <= 0) index = ZERO_BAND_INDEX;
    else if (score >= 100) index = FULL_BAND_INDEX;
    else {
      const middle = MIDDLE_BAND_UPPERS.findIndex((upper) => score <= upper);
      index = 1 + (middle === -1 ? MIDDLE_BAND_UPPERS.length : middle);
    }
    bands[index].share += share;
  }
  return bands;
}

/** 折れ点が実データに対して極端すぎないかの警告（`scoreBands`の帯を受ける）。無ければ空配列。 */
export function distributionWarnings(bands: readonly ScoreBand[]): string[] {
  const warnings: string[] = [];
  const full = bands[FULL_BAND_INDEX].share;
  const zero = bands[ZERO_BAND_INDEX].share;
  if (full >= 0.5) {
    warnings.push(`延長の${Math.round(full * 100)}%が満点に張り付きます。上限を高くしないと道の差が出ません。`);
  }
  if (zero >= 0.9) {
    warnings.push(`延長の${Math.round(zero * 100)}%が0点です。下限を下げないとほとんどの道が同じ評価になります。`);
  }
  return warnings;
}
