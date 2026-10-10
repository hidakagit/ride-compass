"use client";

import * as RadixToggleGroup from "@radix-ui/react-toggle-group";
import { cva, type VariantProps } from "class-variance-authority";
import { createContext, useContext } from "react";
import { cn } from "@/lib/cn";

// 並んだ選択肢から1つを選ぶ。選択状態（role="radio"・aria-checked・data-state）と矢印キーでの
// 移動はRadix ToggleGroupが持つ。
//
// 選んでいるものをもう一度押しても外れない（「選ばない」が無い選択）。
const groupVariants = cva("inline-flex", {
  variants: {
    variant: {
      /** 横に並ぶ切り替え（周回／目的地）。 */
      segmented: "overflow-hidden rounded-full border border-[var(--color-border)]",
      /** 札を横へ流して選ぶ（レンズの軸）。 */
      chips: "w-full flex-wrap gap-1",
    },
  },
  defaultVariants: { variant: "segmented" },
});

const itemVariants = cva(
  "inline-flex min-h-6 min-w-6 cursor-pointer items-center whitespace-nowrap border-0 transition-colors disabled:cursor-default disabled:opacity-50",
  {
    variants: {
      variant: {
        segmented:
          "bg-transparent px-3 py-1.5 text-[length:var(--font-size-xs)] text-[var(--foreground)] data-[state=on]:bg-[var(--color-accent)] data-[state=on]:text-white",
        chips:
          "gap-1 rounded-full border border-[var(--color-border)] bg-transparent px-2 py-0.5 text-inherit hover:bg-[var(--color-surface-hover)] data-[state=on]:border-[var(--color-accent)] data-[state=on]:bg-[var(--color-accent-soft)] data-[state=on]:font-semibold",
      },
    },
    defaultVariants: { variant: "segmented" },
  },
);

type Variant = NonNullable<VariantProps<typeof groupVariants>["variant"]>;
const VariantContext = createContext<Variant>("segmented");

interface ToggleGroupProps extends VariantProps<typeof groupVariants> {
  value: string;
  onValueChange: (value: string) => void;
  "aria-label": string;
  className?: string;
  /** 使い方の文（`Button`の`usage`と同じ）。文を持たない選択肢を押したときも、これを出す。 */
  usage?: string;
  children: React.ReactNode;
}

export function ToggleGroup({ variant, value, onValueChange, className, usage, children, ...props }: ToggleGroupProps) {
  const v = variant ?? "segmented";
  return (
    <VariantContext.Provider value={v}>
      <RadixToggleGroup.Root
        type="single"
        value={value}
        onValueChange={(next) => {
          if (next === "") return;
          onValueChange(next);
        }}
        className={cn(groupVariants({ variant: v }), className)}
        data-usage={usage}
        {...props}
      >
        {children}
      </RadixToggleGroup.Root>
    </VariantContext.Provider>
  );
}

interface ToggleGroupItemProps extends React.ComponentPropsWithoutRef<typeof RadixToggleGroup.Item> {
  value: string;
  /** 使い方の文（`Button`の`usage`と同じ）。 */
  usage?: string;
}

export function ToggleGroupItem({ className, usage, ...props }: ToggleGroupItemProps) {
  const variant = useContext(VariantContext);
  return <RadixToggleGroup.Item className={cn(itemVariants({ variant }), className)} data-usage={usage} {...props} />;
}
