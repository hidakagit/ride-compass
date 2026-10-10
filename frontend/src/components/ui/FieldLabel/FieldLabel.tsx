"use client";

import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";

// フィールドラベル+情報アイコン。説明の開閉は`InfoPopover`が持つため、呼び出し側は`description`を渡すだけでよい。

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
