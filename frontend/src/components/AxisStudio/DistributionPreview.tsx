"use client";

// 折れ点の効き方を実データの分布として見せるパネル。
//
// 数値の入力欄だけでは折れ点の妥当性を判断できず、公開して地図とルートを見るまで結果が
// 分からない。ここで「延長の何%がどの得点帯に入るか」を編集中に見せる。
// 分布の計算は`scoreDistribution.ts`（DOM非依存の純関数）が行い、このファイルは表示のみ。

import { distributionWarnings, scoreBands, type ValueDistribution } from "./scoreDistribution";
import styles from "./DistributionPreview.module.css";

interface Props {
  distribution: ValueDistribution | null;
  breakpoints: readonly [number, number][];
  loading: boolean;
  error: string | null;
}

/** 分位の並び順（quantilesはdictで順序を持たないため、表示順をここで決める）。 */
const QUANTILE_ORDER = ["p10", "p25", "p50", "p75", "p90", "p99"] as const;

export function DistributionPreview({ distribution, breakpoints, loading, error }: Props) {
  const bands = scoreBands(distribution, breakpoints);
  const warnings = distributionWarnings(bands);
  const maxShare = Math.max(...bands.map((b) => b.share), 0.0001);

  return (
    <section className={styles.panel} aria-label="折れ点の効き方">
      <p className={styles.heading}>この折れ点での得点分布</p>
      {error ? (
        <p className={styles.note}>{error}</p>
      ) : loading && !distribution ? (
        <p className={styles.note}>実データを集計中…</p>
      ) : !distribution ? (
        <p className={styles.note}>材料を選ぶと、実データでの分布が出ます。</p>
      ) : distribution.sample_ways === 0 ? (
        // 抽選した道が1本も値を持たない状態。ルート文脈が要る材料（勾配・風）は
        // Way単位では値が定まらないため、この軸では常にここへ来る。
        // 全帯0.0%のバーと「0本（0km）」を出すと「分布はあるが全部0」と読めてしまう。
        <p className={styles.note}>
          この軸の材料はWay単位では値が定まらないため（ルートの走行方向・時刻が要る材料など）、
          実データでの分布を出せません。
        </p>
      ) : (
        <>
          <p className={styles.note}>
            関東の道路を抽選した{distribution.sample_ways.toLocaleString()}本（
            {distribution.total_km.toLocaleString()}km）を、走る距離で重み付けた割合です。
          </p>
          {bands.map((band) => (
            <div key={band.label} className={styles.row}>
              <span>{band.label}</span>
              <span className={styles.barTrack}>
                <span
                  className={styles.barFill}
                  style={{ width: `${(band.share / maxShare) * 100}%` }}
                />
              </span>
              <span className={styles.share}>{(band.share * 100).toFixed(1)}%</span>
            </div>
          ))}
          <p className={styles.quantiles}>
            材料の合成値:{" "}
            {QUANTILE_ORDER.filter((q) => distribution.quantiles[q] !== undefined)
              .map((q) => `${q}=${distribution.quantiles[q]}`)
              .join("  ")}
          </p>
          {warnings.map((warning) => (
            <p key={warning} className={styles.warning}>
              {warning}
            </p>
          ))}
        </>
      )}
    </section>
  );
}
