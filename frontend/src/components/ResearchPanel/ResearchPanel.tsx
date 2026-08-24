"use client";

import { useResearchEnabled } from "@/hooks/useResearchMode";
import { setResearchEnabled } from "@/lib/researchMode";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";

// 研究モードのトグル。オンにすると評価重みの上書きパネルが生成条件セクションへ現れ、
// 以降の生成結果が実験スロットへ記録されて比較表・地図の重ね描きに使えるようになる。
// デバッグモード（ログ表示専任、DebugPanel）とは独立（改善計画T29の2役分割）。
export default function ResearchPanel() {
  const enabled = useResearchEnabled();

  return (
    <label className="flex items-center gap-[0.3rem] text-[length:var(--font-size-md)]">
      <Checkbox checked={enabled} onCheckedChange={setResearchEnabled} aria-label="研究モード[重み調整・実験スロット]" />
      研究モード[重み調整・実験スロット]
    </label>
  );
}
