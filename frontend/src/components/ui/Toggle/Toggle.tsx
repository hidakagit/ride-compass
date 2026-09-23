"use client";

import * as RadixToggle from "@radix-ui/react-toggle";
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef } from "react";
import { cn } from "@/lib/cn";

// 押して切り替えるボタン（ON/OFF）。押下状態の表示（aria-pressed・data-state）とキーボード操作は
// Radix Toggleが持つ。
//
// 押下状態は呼び出し側が`pressed`で完全に持ち、`onClick`で変える（`onPressedChange`を使わない）。
// `<summary>`の中に置く呼び出し側が`event.preventDefault()`で親のdetails開閉を止めることがあり、
// Radixは既定動作を止められたイベントでは内部の切り替えを飛ばすため。
export const toggleVariants = cva(
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-1 whitespace-nowrap border transition-colors disabled:cursor-default disabled:text-[var(--color-neutral)]",
  {
    variants: {
      variant: {
        /** レイヤーのON/OFFのような、1つの対象を出す・隠すチップ。 */
        chip: "min-h-9 rounded-full border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3.5 py-1 text-[length:var(--font-size-md)] text-[var(--foreground)] shadow-float data-[state=on]:border-[var(--color-accent)] data-[state=on]:bg-[var(--color-accent)] data-[state=on]:text-white",
        /** メニューの1行。ONの間はアクセント色の文字。 */
        menu: "justify-start gap-2 rounded-sm border-0 bg-transparent px-1 py-1.5 text-left text-[length:var(--font-size-sm)] text-[var(--foreground)] hover:bg-[var(--color-surface-2)] data-[state=on]:text-[var(--color-accent-strong)]",
        /** 形を中身と呼び出し側に任せる（アイコン＋ラベルの地図チップ・地点の行等）。 */
        plain: "border-0 bg-transparent text-inherit",
      },
    },
    defaultVariants: { variant: "chip" },
  },
);

interface ToggleProps
  extends
    Omit<React.ComponentPropsWithoutRef<typeof RadixToggle.Root>, "onPressedChange" | "defaultPressed">,
    VariantProps<typeof toggleVariants> {
  pressed: boolean;
}

export const Toggle = forwardRef<HTMLButtonElement, ToggleProps>(function Toggle(
  { className, variant, type = "button", ...props },
  ref,
) {
  return <RadixToggle.Root ref={ref} type={type} className={cn(toggleVariants({ variant }), className)} {...props} />;
});
