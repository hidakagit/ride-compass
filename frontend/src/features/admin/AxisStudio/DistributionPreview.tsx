"use client";

// 折れ点の効き方を実データの分布として見せるパネル。
//
// 数値の入力欄だけでは折れ点の妥当性を判断できず、公開して地図とルートを見るまで結果が
// 分からない。ここで「延長の何%がどの得点帯に入るか」を編集中に見せる。
// 分布の計算は`scoreDistribution.ts`（DOM非依存の純関数）が行い、このファイルは表示のみ。

import { distributionWarnings, scoreBands, type ValueDistribution } from "./scoreDistribution";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";
import { calloutVariants } from "@/components/ui/Callout/Callout";
import { cardVariants } from "@/components/ui/Card/Card";

interface Props {
  distribution: ValueDistribution | null;
  breakpoints: readonly [number, number][];
  loading: boolean;
  error: string | null;
}

/** 届いた分位を、分位の数の順に並べる（quantilesは`p<百分位>`を鍵とするdictで順序を持たない）。
 * どの分位を配るかはbackendが決めるため、鍵の一覧を画面で持たない。 */
function quantilesInOrder(quantiles: Readonly<Record<string, number>>): [string, number][] {
  return Object.entries(quantiles).sort(([a], [b]) => Number(a.slice(1)) - Number(b.slice(1)));
}

export function DistributionPreview({ distribution, breakpoints, loading, error }: Props) {
  const bands = scoreBands(distribution, breakpoints);
  const warnings = distributionWarnings(bands);
  const maxShare = Math.max(...bands.map((b) => b.share), 0.0001);

  return (
    <section
      className={cn(cardVariants({ variant: "outline" }), "mt-3 bg-[var(--color-surface-2)]")}
      aria-label="折れ点の効き方"
    >
      <p className={cn(textVariants({ variant: "heading" }), "mb-2 text-[length:var(--font-size-sm)]")}>
        この折れ点での得点分布
      </p>
      {error ? (
        <p className={cn(textVariants({ variant: "hint" }), "mb-2")}>{error}</p>
      ) : loading && !distribution ? (
        <p className={cn(textVariants({ variant: "hint" }), "mb-2")}>実データを集計中…</p>
      ) : !distribution ? (
        <p className={cn(textVariants({ variant: "hint" }), "mb-2")}>材料を選ぶと、実データでの分布が出ます。</p>
      ) : distribution.sample_ways === 0 ? (
        // 抽選した道が1本も値を持たない状態。ルート文脈が要る材料（勾配・風）は
        // Way単位では値が定まらないため、この軸では常にここへ来る。
        // 全帯0.0%のバーと「0本（0km）」を出すと「分布はあるが全部0」と読めてしまう。
        <p className={cn(textVariants({ variant: "hint" }), "mb-2")}>
          この軸の材料はWay単位では値が定まらないため（ルートの走行方向・時刻が要る材料など）、
          実データでの分布を出せません。
        </p>
      ) : (
        <>
          <p className={cn(textVariants({ variant: "hint" }), "mb-2")}>
            関東の道路を抽選した{distribution.sample_ways.toLocaleString()}本（
            {distribution.total_km.toLocaleString()}km）を、走る距離で重み付けた割合です。
          </p>
          {bands.map((band) => (
            <div
              key={band.label}
              className={cn(
                textVariants({ variant: "hint" }),
                "mb-0.5 grid grid-cols-[4.5rem_1fr_3rem] items-center gap-2",
              )}
            >
              <span>{band.label}</span>
              <span className="h-2.5 overflow-hidden rounded-sm bg-[var(--color-surface)]">
                <span
                  className="block h-full bg-[var(--color-accent)]"
                  style={{ width: `${(band.share / maxShare) * 100}%` }}
                />
              </span>
              <span className="text-right tabular-nums text-[var(--foreground)]">{(band.share * 100).toFixed(1)}%</span>
            </div>
          ))}
          <p className={cn(textVariants({ variant: "hint" }), "tabular-nums")}>
            材料の合成値:{" "}
            {quantilesInOrder(distribution.quantiles)
              .map(([q, value]) => `${q}=${value}`)
              .join("  ")}
          </p>
          {warnings.map((warning) => (
            <p key={warning} className={cn(calloutVariants({ tone: "warning" }), "mt-2")}>
              {warning}
            </p>
          ))}
        </>
      )}
    </section>
  );
}
