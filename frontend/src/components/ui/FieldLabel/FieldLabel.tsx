"use client";

import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";

// フィールドラベル+情報アイコン。タップでも確実に開くクリック式の開閉ボタン
// （MapOverlayControlsのaria-expanded凡例トグルと同じ規約）。説明本体はRadix Popoverで
// フローティング表示する——トリガー位置基準のためDOM上の配置形（div直後 vs テーブル行内等）
// に依存しない。開閉状態は`InfoPopover`が持つため、呼び出し側は`description`を
// 渡すだけでよい。

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
