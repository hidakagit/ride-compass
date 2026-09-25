"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";
import { Rnd } from "react-rnd";
import { Button } from "@/components/ui/Button/Button";

interface FloatingPanelProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** 閉じるボタンの手前に置くパネルごとのボタン。 */
  headerButtons?: ReactNode;
  children: ReactNode;
  /** 開いたときの上端（rem）。既定は天候ヘッダのすぐ下。 */
  topRem?: number;
  widthRem?: number;
  /** 本文の最大の高さ（px）。超えたぶんは本文の中でスクロールする。 */
  maxHeightPx?: number;
}

/** 開発者向けのパネル（デバッグログ・システム状況）の共通の殻。画面に浮かべ、見出しのつまみで動かせる（画面の外へは
 * 出ない）。幅はCSSで画面幅に追従させる（Rndの固定pxにしない）。 */
export default function FloatingPanel({
  open,
  onClose,
  title,
  headerButtons,
  children,
  topRem = 4.25,
  widthRem = 22,
  maxHeightPx = 420,
}: FloatingPanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const rndRef = useRef<Rnd>(null);

  // Rndは左上の絶対pxでしか置けないので、描いた幅を測って中央へ置く（描画の前に走るのでずれた位置は見えない）。
  // 閉じるとアンマウントするので、開き直すたびに中央へ戻る（動かした位置は覚えない）。
  useLayoutEffect(() => {
    if (!open) return;
    const rnd = rndRef.current;
    const el = panelRef.current;
    if (!rnd || !el) return;
    const rootFontSizePx = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const width = el.getBoundingClientRect().width;
    rnd.updatePosition({ x: Math.max(0, (window.innerWidth - width) / 2), y: topRem * rootFontSizePx });
  }, [open, topRem]);

  if (!open) return null;

  return (
    <Rnd
      ref={rndRef}
      default={{ x: 0, y: 0, width: "auto", height: "auto" }}
      bounds="window"
      enableResizing={false}
      dragHandleClassName="floating-panel-drag-handle"
      // Rndの既定のabsoluteはページのスクロールに付いて動くので、画面に固定する。
      style={{ position: "fixed", zIndex: "var(--z-floating-panel)" }}
    >
      <div
        ref={panelRef}
        className="flex flex-col rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] text-[length:var(--font-size-xs)] text-[var(--foreground)] shadow-float"
        style={{
          width: `min(${widthRem}rem, calc(100vw - 2 * var(--space-3)))`,
          maxHeight: `${maxHeightPx}px`,
        }}
      >
        <div className="flex flex-shrink-0 items-center gap-1.5 border-b border-[var(--color-border)] px-2 py-1">
          <div
            className="floating-panel-drag-handle cursor-grab touch-none px-1 text-[var(--color-muted)]"
            role="separator"
            aria-label="ドラッグしてパネルを移動"
            title="ドラッグして移動"
          >
            ⠿
          </div>
          <strong className="min-w-0 flex-1 truncate">{title}</strong>
          <div className="flex items-center gap-2">
            {headerButtons}
            <Button variant="ghost" size="xs" onClick={onClose} aria-label={`${title}を閉じる`}>
              ✕
            </Button>
          </div>
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
      </div>
    </Rnd>
  );
}
