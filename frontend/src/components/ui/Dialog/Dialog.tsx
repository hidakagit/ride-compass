"use client";

import * as RadixDialog from "@radix-ui/react-dialog";
import { cn } from "@/lib/cn";

// 汎用モーダルダイアログ。FloatingPanel(react-rndでドラッグ移動)・BottomSheet
// (自前pointerイベントで高さドラッグ)はドラッグ/リサイズという専用の振る舞いを持つため
// Radix Dialogを使わない自前実装のままにしてある(docs/frontend-design-system.md参照)。
// このDialogは新規の単純なモーダル要求(ドラッグ不要な確認ダイアログ等)向けの土台。
//
// titleを必須propsにすることでアクセシブルな名前を型で強制する(Disclosure/LayerChipと
// 同じ既存方針)。hideTitle指定時はTailwind組み込みのsr-onlyで視覚的にのみ隠す。
// z-indexは既存のBottomSheet(45)より上、地図UIより確実に前面に出るTailwindのz-50を使う。

export const DialogRoot = RadixDialog.Root;

interface DialogContentProps {
  title: string;
  hideTitle?: boolean;
  children: React.ReactNode;
  className?: string;
}

export function DialogContent({ title, hideTitle, children, className }: DialogContentProps) {
  return (
    <RadixDialog.Portal>
      <RadixDialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
      <RadixDialog.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 w-[min(90vw,28rem)] -translate-x-1/2 -translate-y-1/2",
          "rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] p-4 shadow-[var(--shadow-float)]",
          "text-[var(--foreground)]",
          className
        )}
      >
        <RadixDialog.Title className={hideTitle ? "sr-only" : "text-[length:var(--font-size-md)] font-semibold"}>
          {title}
        </RadixDialog.Title>
        <div className="mt-3">{children}</div>
        <RadixDialog.Close
          aria-label="閉じる"
          className="absolute right-3 top-3 rounded-sm text-[length:var(--font-size-md)] text-[var(--foreground)]"
        >
          ✕
        </RadixDialog.Close>
      </RadixDialog.Content>
    </RadixDialog.Portal>
  );
}
