import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

// 本文の中に置く、目に留めてほしい1かたまり（判定の結果・注意・失敗）。
export const calloutVariants = cva("rounded-sm p-2 text-[length:var(--font-size-sm)]", {
  variants: {
    tone: {
      neutral: "bg-[var(--color-surface-2)] text-[var(--color-muted)]",
      warning: "border border-[var(--color-warning)] text-[var(--color-warning-strong)]",
      danger: "bg-[var(--color-danger-muted)] text-[var(--color-danger)]",
    },
  },
  defaultVariants: { tone: "neutral" },
});

interface CalloutProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof calloutVariants> {}

export function Callout({ className, tone, ...props }: CalloutProps) {
  return <div className={cn(calloutVariants({ tone }), className)} {...props} />;
}
