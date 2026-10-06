"use client";

import * as Accordion from "@radix-ui/react-accordion";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

// 1つだけ開閉する見出しと本文（1項目だけのRadix Accordion）。各セクションは互いに独立して開閉する。項目の層は
// display:contentsで透過させ、呼ぶ側のレイアウトに影響させない。
interface DisclosureProps {
  /** 全体を包む要素のid（トリガーではなく領域全体に付く）。 */
  id?: string;
  className?: string;
  /** 見出しの行のクラス。 */
  headerClassName?: string;
  /** 押すと開閉する部分のクラス。 */
  triggerClassName?: string;
  bodyClassName?: string;
  /** 押すと開閉する部分の中身。 */
  summary: ReactNode;
  /** 見出しの行に並べる、開閉とは別の操作（タブ・ボタン等）。トリガー（button）の外に置く（中だとbuttonの入れ子になり、
   * 押すと開閉に巻き込まれる）。 */
  trailing?: ReactNode;
  children: ReactNode;
  /** 渡すと呼ぶ側が開閉の状態を持つ（onOpenChangeと対で使う）。 */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** 見出し（開閉のトリガー）の使い方の文（`Button`の`usage`と同じ）。 */
  usage?: string;
}

const ITEM_VALUE = "content";

export default function Disclosure({
  id,
  className,
  headerClassName,
  triggerClassName,
  bodyClassName,
  summary,
  trailing,
  children,
  open,
  onOpenChange,
  usage,
}: DisclosureProps) {
  const handleValueChange = onOpenChange ? (value: string) => onOpenChange(value === ITEM_VALUE) : undefined;
  const controlledProps =
    open !== undefined
      ? { value: open ? ITEM_VALUE : "", onValueChange: handleValueChange }
      : { onValueChange: handleValueChange };

  const trigger = (
    <Accordion.Header className={cn("m-0 [font:inherit]", !trailing && headerClassName)}>
      <Accordion.Trigger className={cn("block w-full cursor-pointer text-left", triggerClassName)} data-usage={usage}>
        {summary}
      </Accordion.Trigger>
    </Accordion.Header>
  );

  return (
    <Accordion.Root id={id} type="single" collapsible className={className} {...controlledProps}>
      <Accordion.Item value={ITEM_VALUE} className="contents">
        {/* trailingがあるときだけ、見出しの行を包むdivを足してそこへheaderClassNameを渡す（見出しの文言に
            trailingの文言を混ぜない）。 */}
        {trailing ? (
          <div className={headerClassName}>
            {trigger}
            {trailing}
          </div>
        ) : (
          trigger
        )}
        <Accordion.Content className={bodyClassName}>{children}</Accordion.Content>
      </Accordion.Item>
    </Accordion.Root>
  );
}
