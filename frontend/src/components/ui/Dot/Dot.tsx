import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

// 状態を示す小さな丸。色だけで伝えるため、呼び出し側が同じ事実を文字（aria-label・title・隣の文）でも持つ
// （docs/modules/frontend/frontend-design-system.md「状態の伝え方」）。
export const dotVariants = cva("inline-block size-2 shrink-0 rounded-full", {
  variants: {
    tone: {
      /** データの取得中（点滅）。 */
      loading: "animate-pulse bg-current opacity-60",
      /** 取得したが空（中空）。 */
      empty: "border border-current opacity-70",
      error: "bg-[var(--color-danger)]",
      accent: "bg-[var(--color-accent)]",
      warning: "bg-[var(--color-warning-strong)]",
      neutral: "bg-[var(--color-border)]",
      /** 場所だけ取って何も描かない（行の頭をそろえる）。 */
      none: "bg-transparent",
    },
  },
  defaultVariants: { tone: "neutral" },
});

interface DotProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof dotVariants> {}

export function Dot({ className, tone, ...props }: DotProps) {
  return <span className={cn(dotVariants({ tone }), className)} {...props} />;
}
