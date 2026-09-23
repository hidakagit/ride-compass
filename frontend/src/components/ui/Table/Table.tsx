import { cn } from "@/lib/cn";

// 一覧表。表だけが横にはみ出すことがあるため、外枠が横スクロールを持つ（ページ全体は横に動かさない）。
// 数字の列は`numeric`で右寄せ・等幅の数字にする。
export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-x-auto rounded-sm border border-[var(--color-border-muted)]">
      <table className={cn("w-full border-collapse text-[length:var(--font-size-sm)]", className)} {...props} />
    </div>
  );
}

export function TableHead({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("bg-[var(--color-surface-2)]", className)} {...props} />;
}

export function TableBody(props: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody {...props} />;
}

export function TableRow({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("border-b border-[var(--color-border-muted)] last:border-b-0", className)} {...props} />;
}

interface CellProps extends React.TdHTMLAttributes<HTMLTableCellElement> {
  numeric?: boolean;
}

export function TableHeader({
  className,
  numeric,
  ...props
}: CellProps & React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        "whitespace-nowrap px-2 py-1 text-left font-bold text-[var(--color-muted)]",
        numeric && "text-right",
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({ className, numeric, ...props }: CellProps) {
  return (
    <td
      className={cn("px-2 py-1 text-left align-middle", numeric && "text-right tabular-nums", className)}
      {...props}
    />
  );
}
