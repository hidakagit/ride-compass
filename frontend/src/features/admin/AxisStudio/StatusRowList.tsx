import { Callout } from "@/components/ui/Callout/Callout";
import { Dot } from "@/components/ui/Dot/Dot";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

/** 点検の1行。名前の右に規模を出し、開くと中身（項目と値）を読む。 */
export interface StatusRow {
  name: string;
  /** 名前の右に出す規模（行数・件数）。 */
  scale: string;
  /** 手当てが要るか（作り直し・注意）。 */
  flagged: boolean;
  detail: { label: string; value: string }[];
  note?: string;
}

/** 点検の結果の一言。手当てが要るものがあれば目立たせ、中身（打つコマンド等）を添えられる。 */
export function StatusVerdict({ flagged, children }: { flagged: boolean; children: React.ReactNode }) {
  return (
    <Callout
      tone={flagged ? "danger" : "neutral"}
      className="flex flex-wrap items-center gap-2 [&>span:first-child]:font-bold"
    >
      {children}
    </Callout>
  );
}

/** 点検の行の一覧。まとまりの見出しが要るときだけ`title`を持たせる。丸の色は手当ての要否で、同じことを
 * 読み上げ用の文（`flaggedLabel`・`okLabel`）でも持つ。 */
export function StatusRowList({
  groups,
  flaggedLabel,
  okLabel,
}: {
  groups: { title?: string; rows: StatusRow[] }[];
  flaggedLabel: string;
  okLabel: string;
}) {
  return (
    <ul className="m-0 flex list-none flex-col p-0">
      {groups.flatMap((group) => [
        ...(group.title
          ? [
              <li key={`title:${group.title}`} className={cn(textVariants({ variant: "note" }), "mt-2")}>
                {group.title}
              </li>,
            ]
          : []),
        ...group.rows.map((row) => (
          <li key={row.name}>
            <details className="border-b border-[var(--color-border)]">
              <summary className="flex cursor-pointer list-none items-center gap-2 py-2 [&::-webkit-details-marker]:hidden">
                <Dot tone={row.flagged ? "error" : "neutral"} aria-hidden="true" />
                <span
                  className={cn(
                    textVariants({ variant: "code" }),
                    "min-w-0 flex-auto text-[length:var(--font-size-sm)]",
                  )}
                >
                  {row.name}
                </span>
                <span className={cn(textVariants({ variant: "note" }), "flex-none tabular-nums")}>{row.scale}</span>
                <span className="sr-only">{row.flagged ? flaggedLabel : okLabel}</span>
              </summary>
              <dl className="mb-2 flex flex-col gap-0.5 pl-4">
                {row.detail.map((item) => (
                  <div key={item.label} className="flex flex-wrap gap-2 text-[length:var(--font-size-sm)]">
                    <dt className="m-0 min-w-20 flex-none text-[var(--color-muted)]">{item.label}</dt>
                    <dd className="m-0 min-w-0 flex-auto tabular-nums [overflow-wrap:anywhere]">{item.value}</dd>
                  </div>
                ))}
              </dl>
              {row.note && <p className={cn(textVariants({ variant: "note" }), "mb-2 pl-4")}>{row.note}</p>}
            </details>
          </li>
        )),
      ])}
    </ul>
  );
}
