import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

// ログの1行。重大度（エラー・警告）の行だけを、左の線と色で目立たせる。
const logLineVariants = cva(
  "border-l-2 border-transparent px-1 py-px font-mono text-[length:var(--font-size-xs)] leading-[1.4] whitespace-pre-wrap break-all",
  {
    variants: {
      tone: {
        normal: "",
        warning:
          "border-[var(--color-warning-strong)] bg-[var(--color-warning-soft)] text-[var(--color-warning-strong)]",
        error: "border-[var(--color-danger)] bg-[var(--color-danger-muted)] font-semibold text-[var(--color-danger)]",
      },
    },
    defaultVariants: { tone: "normal" },
  },
);

interface LogLineProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof logLineVariants> {}

export function LogLine({ className, tone, ...props }: LogLineProps) {
  return <div className={cn(logLineVariants({ tone }), className)} {...props} />;
}
