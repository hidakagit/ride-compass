"use client";

import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";

/** 入力欄の名前と、その脇の(i)。説明の開閉と浮かべ方は`InfoPopover`が持つので、呼び出し側は`description`を渡すだけでよく、表の行の中に置いても並びを崩さない。 */
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
