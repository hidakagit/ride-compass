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
  /** 指定するとトリガーの手前に見出し文言を描画し、見出しとトリガーを1つの要素で囲む
   * （フォーム項目のラベル脇に(i)を置く形）。省略時はトリガー単体。 */
  label?: ReactNode;
  labelClassName?: string;
  /** トリガーボタンの中身。省略時は(i)アイコン。凡例チップのように、見出しそのものを
   * 押させたい呼び出し側が差し替える（アクセシブル名は`triggerAriaLabel`が担うため
   * 中身を変えても読み上げは変わらない）。 */
  triggerContent?: ReactNode;
  children: ReactNode;
}

/** 見出し脇の(i)を押すと、言葉・数値の意味を短い説明で開く。 */
export default function InfoPopover({
  triggerClassName,
  triggerAriaLabel,
  label,
  labelClassName,
  triggerContent,
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
        usage="隣の言葉・数値の意味を開きます。"
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
          {label}
          {trigger}
        </span>
      )}
      <PopoverContent tone="note" side="bottom" align="start">
        {children}
      </PopoverContent>
    </Popover>
  );
}
