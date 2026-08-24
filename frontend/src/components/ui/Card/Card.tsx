import { cn } from "@/lib/cn";

// カード状コンテナ(改善計画T299)。page.module.css .legendCardとadmin.module.css .card
// がバイト単位で同一実装(background: var(--color-surface-2); border-radius:
// var(--radius-md); padding: var(--space-2);)だったため、その定義へそのまま合わせて
// 1つの共通コンポーネントに集約する(既存2箇所どちらも枠線を持たないため、ここでも
// 枠線は付けない)。ComparisonPanel/RouteSettingsPanel/MapLayersPanelの.panelは背景・
// 枠線を持たない縦積みレイアウトのみのため対象が異なり、Cardではなく
// Tailwindユーティリティ(flex flex-col gap-*)を各コンポーネント側で直接使う
// (docs/frontend-design-system.md参照)。
export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-md bg-[var(--color-surface-2)] p-2", className)} {...props} />;
}
