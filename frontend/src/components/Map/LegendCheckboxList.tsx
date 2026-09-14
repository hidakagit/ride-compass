"use client";

import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import type { LegendEntry } from "./legendFilter";

interface LegendCheckboxListProps {
  legend: readonly LegendEntry[];
  hiddenKeys: readonly string[];
  onToggle: (key: string) => void;
  listClassName: string;
  rowClassName: string;
  /** 「不明・他」等の受け皿カテゴリ（LegendEntry.isFallback）専用の追加class。
   * 未指定の呼び出し元はisFallbackを特別扱いしない。 */
  rowFallbackClassName?: string;
  /** widthを持たないLegendEntry（色のみで区別する軸）のスウォッチに使うclass。 */
  swatchClassName: string;
}

// 凡例をチェックボックス一覧として描画する共通部品（MapOverlayControls.tsx・
// RouteAxisProfile.tsx等で共用）。行の中身（チェックボックス+スウォッチ+ラベル）
// だけを担い、リスト/行自体の見た目
// （サイドバーの2列グリッドか、ポップオーバー内の単列か等）は呼び出し側がclassNameで
// 指定する——文脈で項目数・レイアウトが異なるため。
export default function LegendCheckboxList({
  legend,
  hiddenKeys,
  onToggle,
  listClassName,
  rowClassName,
  rowFallbackClassName,
  swatchClassName,
}: LegendCheckboxListProps) {
  return (
    <div className={listClassName}>
      {legend.map((entry) => {
        const visible = !hiddenKeys.includes(entry.key);
        const className =
          entry.isFallback && rowFallbackClassName ? `${rowClassName} ${rowFallbackClassName}` : rowClassName;
        return (
          <label key={entry.key} className={className}>
            <Checkbox checked={visible} onCheckedChange={() => onToggle(entry.key)} aria-label={entry.label} />
            <span aria-hidden="true" className={swatchClassName} style={{ background: entry.color }} />
            {entry.label}
          </label>
        );
      })}
    </div>
  );
}
