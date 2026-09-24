"use client";

import * as RadixPopover from "@radix-ui/react-popover";
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef } from "react";
import { cn } from "@/lib/cn";

// 押すと開く浮きパネル。開閉・位置取り・外側を押したら閉じる・Escで閉じるはRadix Popoverが持つ。
// 中身はdocument.body直下へ描く（呼び出し側がoverflowで切り取る容器の中にあっても欠けない）。
export const Popover = RadixPopover.Root;
export const PopoverTrigger = RadixPopover.Trigger;

const contentVariants = cva(
  "rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2 text-[length:var(--font-size-sm)] leading-[1.4] text-[var(--foreground)] shadow-float",
  {
    variants: {
      /** 重なり順（globals.cssの--z-*）。`top`は開いた時点で必ず見えるべきもの（下部シート・ダイアログより上）、
       * `header`はヘッダーから開くもの（開発者向けの浮きパネルより下）。 */
      layer: {
        top: "z-[var(--z-top-popover)]",
        header: "z-[var(--z-header-popover)]",
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
  { className, layer, tone, sideOffset = 6, ...props },
  ref,
) {
  return (
    <RadixPopover.Portal>
      <RadixPopover.Content
        ref={ref}
        sideOffset={sideOffset}
        className={cn(contentVariants({ layer, tone }), className)}
        {...props}
      />
    </RadixPopover.Portal>
  );
});
