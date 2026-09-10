"use client";

// 材料の値が実データでどこに散らばっているかの1行表示。折れ点をどこへ置くかの当たりを
// つけるためのもので、取得できないときは何も出さない（編集の補助情報のため）。

import { useMaterialDistribution } from "@/hooks/useMaterialDistribution";
import styles from "./DistributionPreview.module.css";

/** 表示する分位。中央値と上側だけを出す（下側は0に張り付く材料が多く情報量が無い）。 */
const SHOWN = ["p50", "p75", "p90"] as const;

export function MaterialRangeHint({
  materialId,
  unit,
  className,
}: {
  materialId: string;
  unit?: string;
  /** 置き場所（行内での回り込み等）は呼び出し側が足す。この部品は中身だけを持つ。 */
  className?: string;
}) {
  const { distribution } = useMaterialDistribution(materialId);
  if (!distribution?.available) return null;
  const parts = SHOWN.filter((q) => distribution.quantiles[q] !== undefined).map(
    (q) => `${q}=${distribution.quantiles[q]}`,
  );
  if (parts.length === 0) return null;
  return (
    <p className={className ? `${styles.quantiles} ${className}` : styles.quantiles}>
      実データ: {parts.join("  ")}
      {unit ? ` (${unit})` : ""}
      {distribution.zero_share > 0 ? `  ゼロ${Math.round(distribution.zero_share * 100)}%` : ""}
    </p>
  );
}
