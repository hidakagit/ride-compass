import { cva } from "class-variance-authority";

// 文字の役割ごとの見た目（大きさ・太さ・色）。文字の大きさは--font-size-*の3段と、ページ見出しだけ。
// 画面は役割を選ぶだけで、大きさや色を直に書かない。
export const textVariants = cva("", {
  variants: {
    variant: {
      /** ページの見出し。 */
      title: "text-[1.4rem] font-bold",
      /** 区分・パネルの見出し。 */
      heading: "text-[length:var(--font-size-md)] font-bold",
      /** 見出しより小さい、まとまりの名前。 */
      label: "text-[length:var(--font-size-sm)] font-bold text-[var(--color-muted)]",
      body: "text-[length:var(--font-size-sm)]",
      /** 補足の説明。 */
      hint: "text-[length:var(--font-size-sm)] text-[var(--color-muted)]",
      /** 数値の単位・件数のような、いちばん小さい補足。 */
      note: "text-[length:var(--font-size-xs)] text-[var(--color-muted)]",
      error: "text-[length:var(--font-size-sm)] text-[var(--color-danger)]",
      /** 識別子・コマンド・ログのような、そのまま読む文字列。 */
      code: "font-mono text-[length:var(--font-size-xs)] [overflow-wrap:anywhere]",
    },
  },
  defaultVariants: { variant: "body" },
});
