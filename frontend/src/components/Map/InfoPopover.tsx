"use client";

import * as Popover from "@radix-ui/react-popover";
import { InfoIcon } from "./icons";

interface InfoPopoverProps {
  triggerClassName: string;
  triggerAriaLabel: string;
  contentClassName: string;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  sideOffset?: number;
  children: React.ReactNode;
}

// 見出し脇の(i)アイコン→ポップオーバーという構造（トリガー+Popover.Root/Trigger/
// Portal/Content）の共通部品。軸チップの説明文（RouteAxisProfile.tsx/
// RouteSettingsPanel.tsx: legendInfoButton）・重み配分/地図の色分けの凡例一覧（同:
// stackBarLegendTrigger）等で共用する。外枠だけを担い、中身は呼び出し側がchildrenで
// 渡す（説明テキストそのまま・凡例一覧いずれも対応）。
export default function InfoPopover({
  triggerClassName,
  triggerAriaLabel,
  contentClassName,
  side = "bottom",
  align = "start",
  sideOffset = 6,
  children,
}: InfoPopoverProps) {
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" className={triggerClassName} aria-label={triggerAriaLabel}>
          <InfoIcon />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className={contentClassName} side={side} align={align} sideOffset={sideOffset}>
          {children}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
