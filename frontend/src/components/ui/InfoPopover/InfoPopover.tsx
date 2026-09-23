"use client";

import { useState, type ReactNode } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import { InfoIcon } from "@/components/ui/icons/icons";
import { Button } from "@/components/ui/Button/Button";

interface InfoPopoverProps {
  /** 置き場に合わせた余白・大きさ（見た目の土台は(i)のボタン）。 */
  triggerClassName?: string;
  /** (i)ボタンのアクセシブル名の**主語**（例:「欠損割合の見方」）。開閉状態に応じて
   * 「◯◯を表示」「◯◯を隠す」を組み立てるため、呼び出し側は動詞を含めない。 */
  triggerAriaLabel: string;
  /** 幅など、置き場に合わせた足し分（見た目の土台は(i)から開く短い説明の浮きパネル）。 */
  contentClassName?: string;
  /** 指定するとトリガーの手前に見出し文言を描画し、見出しとトリガーを1つの要素で囲む
   * （フォーム項目のラベル脇に(i)を置く形）。省略時はトリガー単体。 */
  label?: ReactNode;
  labelClassName?: string;
  /** trueの場合、見出し文言はsr-onlyで視覚的にのみ隠す（アイコン単体の見た目にしたい
   * 呼び出し側向け。アクセシブル名は`triggerAriaLabel`が担うため読み上げは変わらない）。 */
  hideLabel?: boolean;
  /** トリガーボタンの中身。省略時は(i)アイコン。凡例チップのように、見出しそのものを
   * 押させたい呼び出し側が差し替える（アクセシブル名は`triggerAriaLabel`が担うため
   * 中身を変えても読み上げは変わらない）。 */
  triggerContent?: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  sideOffset?: number;
  children: ReactNode;
}

// 見出し脇の(i)アイコン→ポップオーバーという構造（開閉state＋Popover.Root/Trigger/
// Portal/Content＋開閉に追随するアクセシブル名）の共通部品。軸チップの説明文・重み配分/
// 地図の色分けの凡例一覧・軸スタジオの材料説明・フォーム項目のラベル脇で共用する。
// 外枠だけを担い、中身は呼び出し側がchildrenで渡す。
export default function InfoPopover({
  triggerClassName,
  triggerAriaLabel,
  contentClassName,
  label,
  labelClassName,
  hideLabel,
  triggerContent,
  side = "bottom",
  align = "start",
  sideOffset = 6,
  children,
}: InfoPopoverProps) {
  const [open, setOpen] = useState(false);
  const trigger = (
    <PopoverTrigger asChild>
      <Button
        variant="info"
        size="bare"
        className={triggerClassName}
        aria-label={`${triggerAriaLabel}を${open ? "隠す" : "表示"}`}
      >
        {triggerContent ?? <InfoIcon />}
      </Button>
    </PopoverTrigger>
  );
  return (
    <Popover open={open} onOpenChange={setOpen}>
      {label === undefined ? (
        trigger
      ) : (
        <span className={labelClassName}>
          {hideLabel ? <span className="sr-only">{label}</span> : label}
          {trigger}
        </span>
      )}
      <PopoverContent tone="note" className={contentClassName} side={side} align={align} sideOffset={sideOffset}>
        {children}
      </PopoverContent>
    </Popover>
  );
}
