"use client";

import { Fragment } from "react";

import { Button } from "@/components/ui/Button/Button";
import { cardVariants } from "@/components/ui/Card/Card";
import { textVariants } from "@/components/ui/Text/Text";
import { editDifference, formatDelta, roundToDigits } from "@/features/route/routeEditDiff";
import { cn } from "@/lib/cn";
import type { RouteCandidate } from "@/types/route";

interface EditDifferenceProps {
  /** 元にしたルートの一覧での名前（例: `2`・`編集1`・`最速`）。 */
  originName: string;
  origin: RouteCandidate;
  edited: RouteCandidate;
  /** 元のルートへ切り替える。 */
  onShowOrigin: () => void;
}

/**
 * 編集で作ったルートの中身の先頭に出す「元との違い」: 元の名前と距離・変えた区間の数、ルート結果と同じ指標の差、
 * 変えた区間（元の何km〜何km）ごとの長さの差。差の色は編集面（`RouteSplicePanel`）と同じく、減ったら楽になった側の色。
 */
export default function EditDifference({ originName, origin, edited, onShowOrigin }: EditDifferenceProps) {
  const difference = editDifference(origin, edited);
  const metrics: { label: string; value: number | null; digits: number; unit: string }[] = [
    { label: "距離", value: difference.distanceKm, digits: 1, unit: "km" },
    {
      label: "所要",
      value: difference.durationSeconds === null ? null : difference.durationSeconds / 60,
      digits: 0,
      unit: "分",
    },
    { label: "総合難易度", value: difference.difficulty, digits: 0, unit: "" },
    { label: "負荷", value: difference.load, digits: 0, unit: "" },
  ];

  return (
    <section
      className={cn(cardVariants({ variant: "muted" }), "flex flex-col gap-1 text-[length:var(--font-size-md)]")}
      aria-label="元との違い"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <h3 className={cn(textVariants({ variant: "heading" }), "font-semibold whitespace-nowrap")}>元との違い</h3>
        <Button size="xs" onClick={onShowOrigin} usage="元にしたルートへ切り替えます。">
          元を見る
        </Button>
      </div>
      <p className={cn(textVariants({ variant: "hint" }), "m-0")}>
        {/* 狭い幅では「から」の前で折り返す（数と単位の間で切れると読めない）。 */}
        <span className="whitespace-nowrap">
          元: {originName} {origin.distance_km.toFixed(1)}km
        </span>{" "}
        <span className="whitespace-nowrap">から{difference.stretches.length}区間</span>
      </p>
      <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-0.5">
        {metrics.map((metric) => {
          const shown = metric.value === null ? null : roundToDigits(metric.value, metric.digits);
          return (
            <Fragment key={metric.label}>
              <dt className={textVariants({ variant: "note" })}>{metric.label}</dt>
              <dd
                className="m-0 text-right font-bold tabular-nums data-[better=true]:text-[var(--color-accent)] data-[worse=true]:text-[var(--color-route-splice)]"
                data-worse={shown !== null && shown > 0}
                data-better={shown !== null && shown < 0}
              >
                {metric.value === null ? "—" : `${formatDelta(metric.value, metric.digits)}${metric.unit}`}
              </dd>
            </Fragment>
          );
        })}
      </dl>
      {difference.stretches.length > 0 && (
        <ul className={cn(textVariants({ variant: "hint" }), "m-0 flex list-none flex-col gap-0.5 p-0")}>
          {difference.stretches.map((stretch) => (
            <li className="flex justify-between gap-2 whitespace-nowrap tabular-nums" key={stretch.startKm}>
              <span>
                {stretch.startKm.toFixed(1)}〜{stretch.endKm.toFixed(1)}km
              </span>
              <span>{formatDelta(stretch.lengthDiffKm, 1)}km</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
