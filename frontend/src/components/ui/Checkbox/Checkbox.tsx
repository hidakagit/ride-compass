import * as RadixCheckbox from "@radix-ui/react-checkbox";
import { cn } from "@/lib/cn";

// 汎用チェックボックス(改善計画T299)。既存はtype="checkbox"のinput要素を7箇所超で
// 個別実装しており共通コンポーネントが無かった。Radix Checkboxはindeterminate状態
// (Disclosure/LayerChip等と同じ既存のRadix採用パターンを踏襲)をネイティブのinputより
// 表現しやすいため採用する。
export interface CheckboxProps {
  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
  className?: string;
}

export function Checkbox({ checked, defaultChecked, onCheckedChange, disabled, id, className, ...props }: CheckboxProps) {
  return (
    <RadixCheckbox.Root
      id={id}
      checked={checked}
      defaultChecked={defaultChecked}
      onCheckedChange={(state) => onCheckedChange?.(state === true)}
      disabled={disabled}
      className={cn(
        "flex h-[1.1rem] w-[1.1rem] shrink-0 items-center justify-center rounded-sm border border-[var(--color-border-strong)] bg-[var(--color-surface)]",
        "data-[state=checked]:border-[var(--color-accent)] data-[state=checked]:bg-[var(--color-accent)]",
        "disabled:cursor-default disabled:opacity-55",
        className
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
