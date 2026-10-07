import type { ReactNode } from "react";
import type { CatalogAxis } from "@/lib/catalogAxis";
import { formatDifficulty } from "@/lib/mapDisplay/valueScale";

interface AxisDetailProps {
  axis: CatalogAxis;
  /** 重みを掛ける前の、この軸単体の難易度（0-100）。値が来ない軸はundefined。 */
  difficulty: number | undefined;
  /** 評価軸ごとの難易度と説明の間に足す行。 */
  children?: ReactNode;
}

/** 内訳のチップを押して開く軸の詳細（名前・評価軸ごとの難易度・説明）。ルート全体の内訳・区間の詳細・道の詳細が同じ形で出す。 */
export default function AxisDetail({ axis, difficulty, children }: AxisDetailProps) {
  return (
    <>
      <span className="block font-medium">{axis.label}</span>
      <span className="mt-1 block tabular-nums">
        {/* チップの数字（重み付き寄与度）とは別の値。 */}
        {difficulty == null ? "データなし" : `この評価軸の難易度 ${formatDifficulty(difficulty)}/100`}
      </span>
      {children}
      <span className="mt-2 block text-[var(--color-muted)]">{axis.description}</span>
    </>
  );
}
