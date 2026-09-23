import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

// 行や名前の横に添える短い札（「未使用」「非表示」「合成」等）。
export const badgeVariants = cva(
  "inline-flex shrink-0 items-center whitespace-nowrap rounded-sm px-1 text-[length:var(--font-size-xs)] leading-[1.4]",
  {
    variants: {
      variant: {
        /** 使われていない・注意して読む。 */
        warning: "bg-[var(--color-warning-soft)] text-[var(--color-warning-strong)]",
        /** 状態の添え書き（非表示等）。 */
        outline: "rounded-full border border-[var(--color-border-strong)] px-1.5 text-[var(--color-neutral)]",
        /** 補足の区別（合成・最速等）。 */
        muted: "bg-[var(--color-surface-2)] text-[var(--color-muted)]",
      },
    },
    defaultVariants: { variant: "muted" },
  },
);

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
