import { cn } from "@/lib/cn";

// 一覧表。表だけが横にはみ出すことがあるため、外枠が横スクロールを持つ（ページ全体は横に動かさない）。
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

export function TableHeader({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn("whitespace-nowrap px-2 py-1 text-left font-bold text-[var(--color-muted)]", className)}
      {...props}
    />
  );
}

export function TableCell({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-2 py-1 text-left align-middle", className)} {...props} />;
}
