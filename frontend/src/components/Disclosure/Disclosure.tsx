"use client";

import * as Accordion from "@radix-ui/react-accordion";
import type { ReactNode } from "react";
import styles from "./Disclosure.module.css";

// ネイティブ<details>/<summary>の共通置き換え（T254、UIライブラリ導入Phase2）。
// 常に1項目だけを持つRadix Accordion（type="single" collapsible）として実装する
// （複数セクションを排他制御するアコーディオン群ではなく、各セクションが独立して
// 開閉する既存の<details>と同じ挙動を再現するのが目的のため）。
//
// DOM構造は<details class=X><summary class=Y>...</summary><div class=Z>...</div></details>を
// <div class=X><h3 class=Y>...</h3><div class=Z>...</div></div>（trailing無し）または
// <div class=X><div class=Y><h3>...</h3>{trailing}</div><div class=Z>...</div></div>
// （trailingあり、button内buttonを避けるためh3の外に置く）へ写す。Accordion.Item
// （常に1つしか無く見た目上の意味を持たない層）はdisplay:contentsで透過させ、
// 呼び出し側のCSS（親のflex/grid・隣接セレクタ等）への影響を最小化する。
interface DisclosureProps {
  /** 開閉全体を包む要素（旧<details id>相当）のid。旧<details>はidをコンテナ自身に
   * 持たせる用途（テストでの領域スコープ・要素検索）で使われていたため、Trigger単体では
   * なくRoot（コンテナ）へ付ける。開閉のクリックだけをプログラムから行いたい場合は
   * `document.getElementById(id)?.querySelector("button")?.click()`のようにトリガーを
   * 辿る（MapLayersPanel.test.tsxのopenSection参照）。 */
  id?: string;
  /** 開閉全体を包む要素（旧<details>相当）のクラス */
  className?: string;
  /** 見出し行（旧<summary>相当、常に1項目のためh3で描画される）のクラス */
  headerClassName?: string;
  /** クリックで開閉する部分（見出しテキスト・chevron等）のクラス */
  triggerClassName?: string;
  /** 本文（旧<summary>直後のdiv相当）のクラス */
  bodyClassName?: string;
  /** トリガー内に表示する見出し内容（テキスト・chevron等） */
  summary: ReactNode;
  /** 見出し行のうち開閉トリガーの外に置く要素（LayerChip等の独立したボタン）。
   * トリガー（button）の中へネストすると button内button という無効なHTMLになるため、
   * 見出し行（h3）内のトリガーと兄弟として配置する（クリックしても開閉に巻き込まれない）。 */
  trailing?: ReactNode;
  children: ReactNode;
  /** 非制御時の初期状態 */
  defaultOpen?: boolean;
  /** 呼び出し側が状態を持つ制御コンポーネントにする場合に指定（openと対で使う） */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
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
  defaultOpen,
  open,
  onOpenChange,
}: DisclosureProps) {
  const handleValueChange = onOpenChange ? (value: string) => onOpenChange(value === ITEM_VALUE) : undefined;
  const controlledProps =
    open !== undefined
      ? { value: open ? ITEM_VALUE : "", onValueChange: handleValueChange }
      : { defaultValue: defaultOpen ? ITEM_VALUE : "", onValueChange: handleValueChange };

  const trigger = (
    <Accordion.Header className={trailing ? styles.header : `${styles.header} ${headerClassName ?? ""}`.trim()}>
      <Accordion.Trigger className={triggerClassName ? `${styles.trigger} ${triggerClassName}` : styles.trigger}>
        {summary}
      </Accordion.Trigger>
    </Accordion.Header>
  );

  return (
    <Accordion.Root id={id} type="single" collapsible className={className} {...controlledProps}>
      <Accordion.Item value={ITEM_VALUE} className={styles.item}>
        {/* trailing（LayerChip等）がある場合のみ、見出し行の視覚的な横並び（flex row）を
            担う素のdivを追加してheaderClassNameをそちらへ渡す。h3（Accordion.Header）自体は
            Triggerだけを包む薄い意味付けに留め、trailingの文言（例:「表示」）がh3の
            textContentへ混入しないようにする（h3のtextContentをテキスト完全一致で検証している
            既存テストが複数あるため）。trailingが無い単純な場合はheaderClassNameをh3自身へ
            適用し、余計なラップ要素を増やさない。 */}
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
