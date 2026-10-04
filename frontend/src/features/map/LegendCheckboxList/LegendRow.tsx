"use client";

import { useId, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button/Button";
import { InfoIcon } from "@/components/ui/icons/icons";
import { cn } from "@/lib/cn";
import type { LegendEntry } from "@/lib/mapDisplay/legendFilter";

/** 凡例の1行と、行の右端の（i）から行のすぐ下に開く説明（`LegendEntry.description`）。説明を持たない行は（i）を
 * 出さない。浮きパネルにしないのは、凡例そのものが▶の浮きパネルの中にあり、重ねると外を押したときにどちらが
 * 閉じるかが読めなくなるため。（i）は行の中身（`children`）の外に置く——チェックボックスの`label`の中に置くと、
 * 押したときに絞り込みまで切り替わる。 */
export default function LegendRow({
  entry,
  className,
  children,
}: {
  entry: LegendEntry;
  className?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const descriptionId = useId();
  if (!entry.description) return <div className={className}>{children}</div>;
  return (
    <div className={cn("flex flex-col", open && "basis-full", className)}>
      <div className="flex items-center gap-1">
        <div className="min-w-0 flex-1">{children}</div>
        <Button
          variant="info"
          size="bare"
          aria-expanded={open}
          aria-controls={open ? descriptionId : undefined}
          aria-label={`${entry.label}の説明を${open ? "隠す" : "表示"}`}
          usage="この行に何が入るかの説明を開きます。"
          onClick={() => setOpen((current) => !current)}
        >
          <InfoIcon />
        </Button>
      </div>
      {open && (
        <p
          id={descriptionId}
          className="mb-1 pl-6 text-[length:var(--font-size-xs)] whitespace-normal text-[var(--color-neutral)]"
        >
          {entry.description}
        </p>
      )}
    </div>
  );
}
