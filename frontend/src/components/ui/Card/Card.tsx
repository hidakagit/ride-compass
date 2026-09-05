import { cn } from "@/lib/cn";

// カード状コンテナ(background: var(--color-surface-2); border-radius: var(--radius-md);
// padding: var(--space-2); 枠線は持たない)。ComparisonPanel/RouteSettingsPanel/
// MapLayersPanelの.panelは背景・
// 枠線を持たない縦積みレイアウトのみのため対象が異なり、Cardではなく
// Tailwindユーティリティ(flex flex-col gap-*)を各コンポーネント側で直接使う
// (docs/frontend-design-system.md参照)。
export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-md bg-[var(--color-surface-2)] p-2", className)} {...props} />;
}
