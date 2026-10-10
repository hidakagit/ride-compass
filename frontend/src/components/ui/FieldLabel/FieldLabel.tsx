"use client";

import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";

/** 入力欄の名前と、その脇の(i)。(i)を押すと説明を浮かべて開くので、表の行の中に置いても並びを崩さない。 */
export function FieldLabel({ label, description }: { label: string; description: string }) {
  return (
    <InfoPopover
      triggerAriaLabel={`${label}の説明`}
      label={label}
      labelClassName="inline-flex shrink-0 items-center gap-1 whitespace-nowrap"
    >
      {description}
    </InfoPopover>
  );
}
