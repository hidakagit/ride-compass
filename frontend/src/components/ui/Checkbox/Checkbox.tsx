import * as RadixCheckbox from "@radix-ui/react-checkbox";
import { cn } from "@/lib/cn";

// 汎用チェックボックス(改善計画T299)。既存はtype="checkbox"のinput要素を7箇所超で
// 個別実装しており共通コンポーネントが無かった。Radix Checkboxはindeterminate状態
// (Disclosure/LayerChip等と同じ既存のRadix採用パターンを踏襲)をネイティブのinputより
// 表現しやすいため採用する。
export interface CheckboxProps {
  checked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  disabled?: boolean;
  "aria-label"?: string;
}

export function Checkbox({ checked, onCheckedChange, disabled, ...props }: CheckboxProps) {
  return (
    <RadixCheckbox.Root
      checked={checked}
      onCheckedChange={(state) => onCheckedChange?.(state === true)}
      disabled={disabled}
      className={cn(
        // p-0/min-h-0: globals.cssの@layer base button{padding:0.5rem 0.9rem}はTailwindの
        // utilitiesレイヤーより弱い(層として負ける)ため通常は無視できるが、padding自体は
        // このコンポーネントが明示的に上書きしていないと「未指定」のまま素通しされる
        // （層の勝敗はプロパティ単位ではなく宣言単位で決まるため）。Checkbox自身がここで
        // 明示することで、グローバル側の個別パッチ（モバイル限定の[role=checkbox]上書き等）に
        // 頼らず単体で正しいサイズになるようにする(改善計画T299フォローアップ)。
        "flex h-[1.1rem] w-[1.1rem] min-h-0 shrink-0 items-center justify-center rounded-sm border border-[var(--color-border-strong)] bg-[var(--color-surface)] p-0",
        "data-[state=checked]:border-[var(--color-accent)] data-[state=checked]:bg-[var(--color-accent)]",
        "disabled:cursor-default disabled:opacity-55"
      )}
      {...props}
    >
      <RadixCheckbox.Indicator>
        <svg width="10" height="8" viewBox="0 0 10 8" fill="none" aria-hidden="true">
          <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </RadixCheckbox.Indicator>
    </RadixCheckbox.Root>
  );
}
