"use client";

import * as RadixPopover from "@radix-ui/react-popover";
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef } from "react";
import { cn } from "@/lib/cn";
import { USAGE_GUIDE_ATTRIBUTE } from "@/components/UsageGuide/usageTarget";

// 押すと開く浮きパネル。開閉・位置取り・外側を押したら閉じる・Escで閉じるはRadix Popoverが持つ。
// 中身はdocument.body直下へ描く（呼び出し側がoverflowで切り取る容器の中にあっても欠けない）。
export const Popover = RadixPopover.Root;
/** 押すと開くボタン。印（`data-usage-opens`）を持ち、説明を見る状態（`components/UsageGuide/UsageGuide.tsx`）は
 * この部品の説明に「中を見る」を出す。 */
export const PopoverTrigger = forwardRef<
  HTMLButtonElement,
  React.ComponentPropsWithoutRef<typeof RadixPopover.Trigger>
>(function PopoverTrigger(props, ref) {
  return <RadixPopover.Trigger ref={ref} data-usage-opens="" {...props} />;
});
/** 押した部品以外の位置へ開くときの目印（`virtualRef`で要素を指す）。 */
export const PopoverAnchor = RadixPopover.Anchor;

/** 画面の端へ寄せて開くとき、端との間に空ける幅（px）。 */
export const POPOVER_COLLISION_PADDING_PX = 8;

const contentVariants = cva(
  "rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2 text-[length:var(--font-size-sm)] leading-[1.4] text-[var(--foreground)] shadow-float",
  {
    variants: {
      /** 重なり順（globals.cssの--z-*）。`top`は開いた時点で必ず見えるべきもの（下部シート・ダイアログより上）、
       * `header`はヘッダーから開くもの（開発者向けの浮きパネルより下）。 */
      layer: {
        top: "z-[var(--z-top-popover)]",
        header: "z-[var(--z-header-popover)]",
        /** 使い方の説明。開いているほかの浮きパネルの上に出す。 */
        guide: "z-[var(--z-usage-guide)]",
      },
      /** `note`は(i)から開く短い説明。幅を絞り、文字を控えめな色にする。 */
      tone: {
        panel: "",
        note: "max-w-64 text-[var(--color-muted)]",
        /** 中身が自分で面を持つとき（時刻のスライダー等）。面を二重にしない。 */
        bare: "border-0 bg-transparent p-0 shadow-none",
      },
    },
    defaultVariants: { layer: "top", tone: "panel" },
  },
);

interface PopoverContentProps
  extends React.ComponentPropsWithoutRef<typeof RadixPopover.Content>, VariantProps<typeof contentVariants> {}

export const PopoverContent = forwardRef<HTMLDivElement, PopoverContentProps>(function PopoverContent(
  { className, layer, tone, sideOffset = 6, onInteractOutside, ...props },
  ref,
) {
  return (
    <RadixPopover.Portal>
      <RadixPopover.Content
        ref={ref}
        sideOffset={sideOffset}
        className={cn(contentVariants({ layer, tone }), className)}
        onInteractOutside={(event) => {
          onInteractOutside?.(event);
          // 説明を見る状態の案内・説明の面を押しても、そこへフォーカスが移っても閉じない（開いたまま、中の部品の説明を見られる）。
          if (event.target instanceof Element && event.target.closest(`[${USAGE_GUIDE_ATTRIBUTE}]`))
            event.preventDefault();
        }}
        {...props}
      />
    </RadixPopover.Portal>
  );
});
