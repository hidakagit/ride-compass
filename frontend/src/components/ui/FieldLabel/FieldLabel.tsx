"use client";

import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { cn } from "@/lib/cn";

// フィールドラベル+情報アイコン。タップでも確実に開くクリック式の開閉ボタン
// （MapOverlayControlsのaria-expanded凡例トグルと同じ規約）。説明本体はRadix Popoverで
// フローティング表示する——トリガー位置基準のためDOM上の配置形（div直後 vs テーブル行内等）
// に依存しない。開閉状態は`InfoPopover`が持つため、呼び出し側は`description`を
// 渡すだけでよい。`className`は置き場に合わせた足し分（表の中で折り返しを許す等）。

export function FieldLabel({
  label,
  description,
  className,
  hideLabel,
}: {
  label: string;
  description: string;
  className?: string;
  /** trueの場合、ラベル文言はTailwindのsr-onlyで視覚的にのみ隠す（アイコン単体の見た目に
   * したい呼び出し側向け。aria-label自体はlabelの値のまま維持されるため読み上げは変わらない）。 */
  hideLabel?: boolean;
}) {
  return (
    <InfoPopover
      triggerAriaLabel={`${label}の説明`}
      label={label}
      labelClassName={cn("inline-flex shrink-0 items-center gap-1 whitespace-nowrap", className)}
      hideLabel={hideLabel}
    >
      {description}
    </InfoPopover>
  );
}
