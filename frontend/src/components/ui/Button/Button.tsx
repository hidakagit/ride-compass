import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef } from "react";
import { cn } from "@/lib/cn";

// 汎用ボタン。variantを明示することで、見た目の決定箇所をこのコンポーネントへ集約する
// （className未指定でglobals.cssのグローバルbutton[type="submit"]リセットに暗黙依存すると、
// 「プライマリボタンの見た目」がどこにも明示されず、将来どこかでtype="submit"のボタンを
// 追加すると意図せず同じ配色を継承してしまう脆弱な結合になるため）。
//
// 色は必ずvar(--color-*)をTailwindの任意値記法で参照する(docs/frontend-design-system.md
// のルール)。primaryはglobals.cssの既存button[type="submit"]配色(--color-accent塗り+
// 白文字)と揃える。
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1 rounded-sm border text-[length:var(--font-size-md)] font-normal transition-colors disabled:cursor-default disabled:opacity-55",
  {
    variants: {
      variant: {
        primary:
          "border-[var(--color-accent)] bg-[var(--color-accent)] text-white font-semibold hover:enabled:bg-[var(--color-accent-strong)] hover:enabled:border-[var(--color-accent-strong)]",
        secondary:
          "border-[var(--color-border-strong)] bg-[var(--color-surface)] text-[var(--foreground)] hover:enabled:border-[var(--color-accent)]",
        ghost: "border-transparent bg-transparent text-[var(--foreground)] hover:enabled:border-[var(--color-border-strong)]",
      },
      size: {
        sm: "px-2 py-1 text-[length:var(--font-size-sm)]",
        md: "px-[0.9rem] py-2",
      },
    },
    defaultVariants: {
      variant: "secondary",
      size: "md",
    },
  }
);

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, type = "button", ...props },
  ref
) {
  return <button ref={ref} type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
});
