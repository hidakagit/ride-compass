import { forwardRef } from "react";
import { cn } from "@/lib/cn";

// 汎用テキスト/数値入力(改善計画T299)。type属性をそのままパススルーするため
// text/numberどちらの既存用途(AxisComposer.tsx等15箇所超で個別実装)にも使える。
// 色は必ずvar(--color-*)を任意値記法で参照する(docs/frontend-design-system.md)。
export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /** true時にaria-invalidを付与し赤枠にする。ErrorTextとの結線は今回は行わない。 */
  invalid?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, invalid, ...props },
  ref
) {
  return (
    <input
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(
        "rounded-sm border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-[0.6rem] py-[0.4rem]",
        "text-[length:var(--font-size-md)] text-[var(--foreground)]",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-accent)] focus-visible:outline-offset-2",
        invalid && "border-[var(--color-danger)]",
        className
      )}
      {...props}
    />
  );
});
