import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

// ひとまとまりの面。並べ方（flex・gap）は呼び出し側が足す。
export const cardVariants = cva("rounded-md", {
  variants: {
    variant: {
      /** 地の色を1段変えて区切る。 */
      muted: "bg-[var(--color-surface-2)] p-2",
      /** 枠線で区切る（管理画面のパネル・編集面）。 */
      outline: "border border-[var(--color-border-muted)] p-3",
      /** 地図の上に浮かせる面。 */
      float: "border border-[var(--color-border-strong)] bg-[var(--color-surface)] shadow-float",
      /** 地図の上に開く内訳。地図を覆いすぎないよう、面を半透明にしてぼかす。 */
      glass:
        "border border-[var(--color-border-strong)] bg-[color-mix(in_srgb,var(--color-surface)_78%,transparent)] shadow-float backdrop-blur-[6px]",
    },
  },
  defaultVariants: { variant: "muted" },
});

interface CardProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof cardVariants> {}

export function Card({ className, variant, ...props }: CardProps) {
  return <div className={cn(cardVariants({ variant }), className)} {...props} />;
}
