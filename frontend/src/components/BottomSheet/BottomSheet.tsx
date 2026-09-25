"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import { Button } from "@/components/ui/Button/Button";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

interface BottomSheetProps {
  open: boolean;
  onClose: () => void;
  /** 見出し（シートのアクセシブル名にもなる）。 */
  title: string;
  titleId: string;
  /** 見出しの行の右、閉じるボタンの手前に置く操作。 */
  headerAction?: React.ReactNode;
  /** 見出しのすぐ右に置くもの（中身を切り替えるタブ等、右の操作と役割が違うもの）。 */
  headerLead?: React.ReactNode;
  children: React.ReactNode;
  /** いま出している高さ（vh）。開いたときに中身へ合わせ直すので、利用者の恒久の設定ではない。 */
  heightVh: number;
  /** ドラッグやキー操作の途中も呼ばれる（見た目へすぐ反映する）。 */
  onHeightChange: (vh: number) => void;
  /** 操作を終えたときだけ呼ばれる（保存用）。 */
  onHeightCommit: (vh: number) => void;
  /** 中身に合わせて高さを決めるか（既定true）。利用者が高さを決めた後はfalseにし、その高さを保つ。 */
  autoFitHeight?: boolean;
  /** 変わったら中身が別物になったとみなして高さを合わせ直す（タブの切り替え等）。 */
  fitKey?: string;
}

const SWIPE_CLOSE_THRESHOLD_PX = 60;

// 上限は地図を隠し切らない高さにする。
const MIN_SHEET_HEIGHT_VH = 20;
const MAX_SHEET_HEIGHT_VH = 80;
export const DEFAULT_SHEET_HEIGHT_VH = 50;
const HEIGHT_KEY_STEP_VH = 5;

export function clampSheetHeightVh(vh: number): number {
  return Math.min(MAX_SHEET_HEIGHT_VH, Math.max(MIN_SHEET_HEIGHT_VH, vh));
}

/** 中身がそのまま並んだときの高さ。高さの指定を一時的に外して測る（`scrollHeight`や子の合算は、中身が箱より
 * 低いと箱の高さを返すので縮める判断に使えない）。読み書きは同じレイアウトの中で終わるので途中の高さは描かれない。 */
function naturalHeightOf(sheet: HTMLElement): number {
  const specified = sheet.style.height;
  sheet.style.height = "auto";
  const natural = sheet.getBoundingClientRect().height;
  sheet.style.height = specified;
  return natural;
}

/** モバイルの下からせり上がるシート。暗幕を敷かず、シートの外を押しても閉じない（開いたまま地図を動かせる）。
 * 閉じるのは✕・下スワイプ・呼ぶ側のタブの押し直し。 */
export default function BottomSheet({
  open,
  onClose,
  title,
  titleId,
  headerAction,
  headerLead,
  children,
  heightVh,
  onHeightChange,
  onHeightCommit,
  autoFitHeight = true,
  fitKey,
}: BottomSheetProps) {
  const sheetRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);

  // 開いたときの中身に合う高さへ合わせる（高すぎると空白で地図を隠す）。開いている間は合わせ直さない（候補や区間を
  // 押すたびに地図の見える範囲が動かないように）。実寸が取れない環境では何もしない。
  useLayoutEffect(() => {
    if (!open || !autoFitHeight) return;
    const sheet = sheetRef.current;
    const body = bodyRef.current;
    if (!sheet || !body) return;
    const viewportHeight = window.innerHeight;
    const needed = naturalHeightOf(sheet);
    if (viewportHeight <= 0 || sheet.clientHeight <= 0 || needed <= 0) return;
    onHeightChange(clampSheetHeightVh(Math.ceil((needed / viewportHeight) * 100)));
  }, [open, onHeightChange, autoFitHeight, fitKey]);
  // つまみのドラッグ。始めた指（pointerId）の動きだけを見る（別の指のmove/upに反応しない）。
  const dragRef = useRef<{ pointerId: number; startClientY: number; startHeightVh: number } | null>(null);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  function handleTouchStart(e: React.TouchEvent) {
    const touch = e.touches[0];
    touchStartRef.current = { x: touch.clientX, y: touch.clientY };
  }

  function handleTouchEnd(e: React.TouchEvent) {
    const start = touchStartRef.current;
    touchStartRef.current = null;
    if (!start) return;
    const touch = e.changedTouches[0];
    const dy = touch.clientY - start.y;
    const dx = touch.clientX - start.x;
    // 縦の下スワイプだけで閉じる（横の動きが大きいのはシート内の横スクロールの操作）。
    if (dy > SWIPE_CLOSE_THRESHOLD_PX && Math.abs(dy) > Math.abs(dx)) {
      onClose();
    }
  }

  function handleHandlePointerDown(e: React.PointerEvent<HTMLDivElement>) {
    dragRef.current = { pointerId: e.pointerId, startClientY: e.clientY, startHeightVh: heightVh };
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function handleHandlePointerMove(e: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || e.pointerId !== drag.pointerId) return;
    const deltaVh = ((drag.startClientY - e.clientY) / window.innerHeight) * 100;
    onHeightChange(clampSheetHeightVh(drag.startHeightVh + deltaVh));
  }

  function handleHandlePointerUp(e: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || e.pointerId !== drag.pointerId) return;
    dragRef.current = null;
    onHeightCommit(heightVh);
  }

  function handleHandleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const direction = e.key === "ArrowUp" ? 1 : e.key === "ArrowDown" ? -1 : 0;
    if (direction === 0) return;
    e.preventDefault();
    const next = clampSheetHeightVh(heightVh + direction * HEIGHT_KEY_STEP_VH);
    onHeightChange(next);
    onHeightCommit(next);
  }

  return (
    // app-bottom-sheetはglobals.cssのモバイル向けの規則（シート内の入力欄・チェックボックスを大きくする）の目印。
    <div
      ref={sheetRef}
      className={cn(
        "fixed right-0 bottom-[var(--mobile-tabbar-height)] left-0 z-[var(--z-bottom-sheet)] flex flex-col rounded-t-lg bg-[var(--background)] shadow-[0_-2px_16px_rgba(0,0,0,0.3)]",
        "app-bottom-sheet",
      )}
      role="dialog"
      aria-labelledby={titleId}
      style={{ height: `${heightVh}vh` }}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      {/* 高さを変える帯。全幅の帯は小さいボタンより押し外しにくいため、縦は44pxより薄くして地図を空ける。 */}
      <div
        className="flex w-full flex-shrink-0 cursor-ns-resize touch-none items-center justify-center py-2 before:h-1 before:w-9 before:rounded-sm before:bg-[var(--color-border-strong)] before:content-[''] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent)]"
        role="separator"
        aria-orientation="horizontal"
        aria-label="パネルの高さを変更"
        aria-valuenow={Math.round(heightVh)}
        aria-valuemin={MIN_SHEET_HEIGHT_VH}
        aria-valuemax={MAX_SHEET_HEIGHT_VH}
        tabIndex={0}
        onPointerDown={handleHandlePointerDown}
        onPointerMove={handleHandlePointerMove}
        onPointerUp={handleHandlePointerUp}
        // つまみのtouchstartがシートの下スワイプの判定まで届くと、ドラッグの後の指離しで閉じてしまう。
        onTouchStart={(e) => e.stopPropagation()}
        onKeyDown={handleHandleKeyDown}
      />
      <div className="flex flex-shrink-0 items-center justify-between gap-2 border-b border-[var(--color-border)] px-3">
        <h2
          id={titleId}
          tabIndex={-1}
          className={cn(textVariants({ variant: "heading" }), "min-w-0 truncate focus:outline-none")}
        >
          {title}
        </h2>
        {headerLead && <div className="mr-auto flex min-w-0 items-center">{headerLead}</div>}
        <div className="flex flex-shrink-0 items-center gap-2">
          {headerAction}
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label="閉じる"
            className="size-7 text-base text-[var(--foreground)]"
          >
            ✕
          </Button>
        </div>
      </div>
      {/* 本文のスクロールが下スワイプの判定まで届かないようにする（届くとスクロールしただけで閉じる）。 */}
      <div
        ref={bodyRef}
        className="flex flex-col gap-2 overflow-y-auto px-3 pt-2 pb-3"
        onTouchStart={(e) => e.stopPropagation()}
        onTouchEnd={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
