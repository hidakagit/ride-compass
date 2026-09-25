import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef } from "react";
import { cn } from "@/lib/cn";

// 押すと1回動く操作のボタン。画面のボタンはすべてこれか、押して切り替える`Toggle`・
// 1つを選ぶ`ToggleGroup`・`Tabs`を使う（見た目はここだけが決める）。
//
// 色は必ずvar(--color-*)をTailwindの任意値記法で参照する(docs/modules/frontend/frontend-design-system.md)。
export const buttonVariants = cva(
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-1 whitespace-nowrap border font-normal leading-none transition-colors disabled:cursor-default disabled:opacity-50 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        /** 画面の主操作（ルート生成・保存）。 */
        primary:
          "border-[var(--color-accent)] bg-[var(--color-accent)] font-semibold text-white hover:enabled:border-[var(--color-accent-strong)] hover:enabled:bg-[var(--color-accent-strong)]",
        secondary:
          "border-[var(--color-border-strong)] bg-[var(--color-surface)] text-[var(--foreground)] hover:enabled:border-[var(--color-accent)] data-[state=open]:border-[var(--color-accent)] data-[state=open]:text-[var(--color-accent)]",
        /** 枠の無い控えめな操作（閉じる・消す・戻る）。 */
        ghost:
          "border-transparent bg-transparent text-[var(--color-muted)] hover:enabled:text-[var(--foreground)] hover:enabled:bg-[var(--color-surface-hover)]",
        danger:
          "border-[var(--color-danger)] bg-[var(--color-surface)] text-[var(--color-danger)] hover:enabled:bg-[var(--color-danger-muted)]",
        warning:
          "border-[var(--color-warning-strong)] bg-transparent text-[var(--color-warning-strong)] hover:enabled:bg-[var(--color-warning-soft)]",
        /** 値を1段ずつ動かす（−／＋、◀／▶）。隣の主役の入力より目立たせないよう枠線だけにする。 */
        stepper:
          "border-[var(--color-border)] bg-transparent font-semibold text-[var(--color-accent)] hover:enabled:border-[var(--color-accent)] disabled:text-[var(--color-muted)]",
        /** 地図の上に浮かせる操作。親が`pointer-events: none`で地図の操作を通すため自分だけ戻す。
         * `touch-action: none`は、2本指のピンチの片方がボタンに乗ったときにブラウザがページの
         * ジェスチャーとして扱い、地図のピンチが効かなくなるのを止める。タップの既定ハイライトは、端末によって
         * 消えるのが遅れ、押した後も枠が青く見えるため消す。 */
        float:
          "pointer-events-auto touch-none border-[var(--color-border-strong)] bg-[var(--color-surface)] text-[var(--foreground)] shadow-float [-webkit-tap-highlight-color:transparent] hover:enabled:border-[var(--color-accent)]",
        /** 地図右上のMapLibre純正コントロールの続きに見えるボタン。MapLibre側がテーマに追従しないため、
         * 同じ列で色違いにならないよう固定色にする。寸法はglobals.cssの--map-ctrl-*（縦積みの位置計算と共有）。 */
        mapCtrl:
          "pointer-events-auto touch-none rounded-[4px] border-0 bg-white text-[#333] shadow-[0_0_0_2px_rgba(0,0,0,0.1)] data-[state=open]:shadow-[0_0_2px_2px_#0096ff] [&_svg]:size-[var(--map-ctrl-icon-size)]",
        /** 見出し脇の(i)。開いている間はアクセント色。 */
        info: "border-0 bg-transparent text-[var(--color-muted)] aria-expanded:text-[var(--color-accent-strong)]",
      },
      size: {
        xs: "rounded-sm px-1.5 py-0.5 text-[length:var(--font-size-xs)]",
        sm: "rounded-sm px-2 py-1 text-[length:var(--font-size-sm)]",
        md: "rounded-sm px-3.5 py-2 text-[length:var(--font-size-md)]",
        /** 四角のアイコンボタン。 */
        icon: "size-8 rounded-sm",
        /** アイコンの横に短い名前を置くボタン。パネルの操作はすべてこの形（縦に積むより低く、下部シートの高さを取らない）。 */
        iconLabel: "gap-1 rounded-sm px-2 py-1 text-[length:var(--font-size-xs)]",
        /** 小さい丸のアイコンボタン。 */
        iconRound: "size-6.5 rounded-full",
        /** 地図右上の列の1段。 */
        mapCtrl: "h-[var(--map-ctrl-button-size)] w-[var(--map-ctrl-column-width)]",
        /** 大きさを中身と呼び出し側に任せる（infoの(i)等）。余白は既定の0のまま。 */
        bare: "",
      },
      shape: {
        default: "",
        pill: "rounded-full",
      },
    },
    defaultVariants: {
      variant: "secondary",
      size: "md",
      shape: "default",
    },
  },
);

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, shape, type = "button", ...props },
  ref,
) {
  return (
    <button ref={ref} type={type} className={cn(buttonVariants({ variant, size, shape }), className)} {...props} />
  );
});
