"use client";

import { useId, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button/Button";
import { InfoIcon } from "@/components/ui/icons/icons";
import { cn } from "@/lib/cn";
import type { LegendEntry } from "@/lib/mapDisplay/legendFilter";

/** 行の右端の（i）。押すと`label`の説明を行のすぐ下に開く。 */
export function DescriptionToggle({
  label,
  open,
  descriptionId,
  usage,
  onToggle,
}: {
  label: string;
  open: boolean;
  descriptionId: string;
  usage: string;
  onToggle: () => void;
}) {
  return (
    <Button
      variant="info"
      size="bare"
      aria-expanded={open}
      aria-controls={open ? descriptionId : undefined}
      aria-label={`${label}の説明を${open ? "隠す" : "表示"}`}
      onClick={onToggle}
      usage={usage}
    >
      <InfoIcon />
    </Button>
  );
}

/** （i）で行のすぐ下に開いた説明。 */
export function RowDescription({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={id} className="mb-1 pl-6 text-[length:var(--font-size-xs)] whitespace-normal text-[var(--color-neutral)]">
      {children}
    </p>
  );
}

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
        <DescriptionToggle
          label={entry.label}
          open={open}
          descriptionId={descriptionId}
          usage="この段階の意味を、行のすぐ下に開きます。"
          onToggle={() => setOpen((current) => !current)}
        />
      </div>
      {open && <RowDescription id={descriptionId}>{entry.description}</RowDescription>}
    </div>
  );
}
