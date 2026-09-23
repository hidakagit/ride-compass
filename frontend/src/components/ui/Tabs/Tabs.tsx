"use client";

import * as RadixTabs from "@radix-ui/react-tabs";
import { cva, type VariantProps } from "class-variance-authority";
import { createContext, forwardRef, useContext } from "react";
import { cn } from "@/lib/cn";

// タブ。選択状態・矢印キーでの移動・パネルの出し分けはRadix Tabsが持つ。Root・Contentは
// 見た目を持たないのでRadixのものをそのまま使い、見た目を持つ列とタブだけをここに置く。
//
// 選択中のタブは下線（縦並びでは左の線）に加えて背景も変える。ダークモードでは、選択中の
// アクセント色と非選択の灰色の文字の差が小さく、線だけでは選択中が読み取れない。
export const Tabs = RadixTabs.Root;
export const TabsContent = RadixTabs.Content;

const listVariants = cva("flex", {
  variants: {
    variant: {
      /** 横に並ぶタブ。狭い画面では折り返さずに列ごと横へ流す（1本が2行の高さになると本文の前に画面を使い切る）。 */
      underline: "gap-1 overflow-x-auto border-b border-[var(--color-border)]",
      /** 縦に並ぶタブ（1行1候補の一覧）。 */
      side: "min-w-0 flex-1 flex-col",
    },
  },
  defaultVariants: { variant: "underline" },
});

const triggerVariants = cva(
  "flex cursor-pointer items-center whitespace-nowrap border-0 bg-transparent font-bold text-[length:var(--font-size-sm)] text-[var(--color-muted)] transition-colors data-[state=active]:text-[var(--color-accent-strong)] disabled:cursor-not-allowed disabled:text-[var(--color-border)]",
  {
    variants: {
      variant: {
        underline:
          "-mb-px flex-none rounded-t-sm border-b-2 border-transparent px-2 py-1.5 data-[state=active]:border-[var(--color-accent-strong)] data-[state=active]:bg-[var(--color-accent-bg)]",
        side: "w-full shrink-0 justify-between gap-1.5 border-l-3 border-transparent px-2 py-1.5 text-left data-[state=active]:border-[var(--color-accent-strong)] data-[state=active]:bg-[var(--color-surface-2)]",
      },
    },
    defaultVariants: { variant: "underline" },
  },
);

type Variant = NonNullable<VariantProps<typeof listVariants>["variant"]>;
const VariantContext = createContext<Variant>("underline");

interface TabsListProps
  extends React.ComponentPropsWithoutRef<typeof RadixTabs.List>, VariantProps<typeof listVariants> {}

export const TabsList = forwardRef<HTMLDivElement, TabsListProps>(function TabsList(
  { className, variant, ...props },
  ref,
) {
  const v = variant ?? "underline";
  return (
    <VariantContext.Provider value={v}>
      <RadixTabs.List ref={ref} className={cn(listVariants({ variant: v }), className)} {...props} />
    </VariantContext.Provider>
  );
});

export const TabsTrigger = forwardRef<HTMLButtonElement, React.ComponentPropsWithoutRef<typeof RadixTabs.Trigger>>(
  function TabsTrigger({ className, ...props }, ref) {
    const variant = useContext(VariantContext);
    return <RadixTabs.Trigger ref={ref} className={cn(triggerVariants({ variant }), className)} {...props} />;
  },
);
