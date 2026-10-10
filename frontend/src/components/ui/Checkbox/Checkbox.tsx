import * as RadixCheckbox from "@radix-ui/react-checkbox";

interface CheckboxProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  "aria-label"?: string;
}

export function Checkbox({ checked, onCheckedChange, ...props }: CheckboxProps) {
  return (
    <RadixCheckbox.Root
      checked={checked}
      onCheckedChange={(state) => onCheckedChange(state === true)}
      // p-0・min-h-0とsize-6は、docs/modules/frontend/frontend-design-system.mdの「`components/ui/`コンポーネント
      // 自身の自己防衛」「タップ領域（44px）は、主要な導線だけが自前で持つ」。見た目の四角は24px四方の中に小さく描く。
      className="group flex size-6 min-h-0 shrink-0 items-center justify-center border-0 bg-transparent p-0 disabled:opacity-40"
      {...props}
    >
      <span className="flex h-[1.1rem] w-[1.1rem] items-center justify-center rounded-sm border border-[var(--color-border-strong)] bg-[var(--color-surface)] group-data-[state=checked]:border-[var(--color-accent)] group-data-[state=checked]:bg-[var(--color-accent)]">
        <RadixCheckbox.Indicator>
          <svg width="10" height="8" viewBox="0 0 10 8" fill="none" aria-hidden="true">
            <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </RadixCheckbox.Indicator>
      </span>
    </RadixCheckbox.Root>
  );
}
