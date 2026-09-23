"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import { Button } from "@/components/ui/Button/Button";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

interface BottomSheetProps {
  open: boolean;
  onClose: () => void;
  /** シートの見出し（アクセシブル名にも使う） */
  title: string;
  /** 見出しのDOM id（シートの`aria-labelledby`が指す）。 */
  titleId: string;
  /** ヘッダ右側、閉じるボタンの手前へ差し込む任意の要素。シートごとの補足説明の
   * 情報アイコン・アクションボタンをヘッダ右上へ集約するための差し込み口（page.tsx:
   * 「ルート結果」シートのrenderRouteResultHeaderActions参照）。 */
  headerAction?: React.ReactNode;
  /** 見出しのすぐ右（左寄せ）に置く差し込み口。中身を切り替えるタブのように、右上の
   * アクション群（headerAction）と役割が違うものを、見た目でも離して置くため。 */
  headerLead?: React.ReactNode;
  children: React.ReactNode;
  /** シートの高さ（vh）。シートは排他表示のため、呼び出し側（page.tsx）が1つの値を
   * 共有して持つ。開いた時点で中身に合う高さへ合わせ直すため（下記useLayoutEffect）、
   * この値は「いま表示している高さ」であって利用者の恒久的な設定ではない。 */
  heightVh: number;
  /** ドラッグ・キー操作の途中も含めて随時呼ばれる（見た目の即時反映用）。 */
  onHeightChange: (vh: number) => void;
  /** ドラッグ終了・キー操作確定時にのみ呼ばれる（永続化用。ドラッグ中の連続書き込みを避ける）。 */
  onHeightCommit: (vh: number) => void;
  /** 中身に合わせた高さの自動調整を行うか（既定true）。利用者が自分で高さを決めた後は
   * falseにして、その高さをそのまま使う——地図を広く見るためにわざと低くしたシートが
   * 中身の都合で戻されると、決めた高さを保てない。 */
  autoFitHeight?: boolean;
  /** 自動調整をやり直す区切り。開いている間は合わせ直さないのが既定だが、この値が
   * 変わったときは中身が別物になったとみなして合わせ直す（タブ・モードの切替等、利用者
   * 自身が別の内容へ移った場合）。 */
  fitKey?: string;
}

const SWIPE_CLOSE_THRESHOLD_PX = 60;

// 「ちょうどいい高さ」はユーザーによって違う（片手操作か両手か、地図をどれだけ見たいか等）
// ため固定値にせず、ハンドルドラッグ/キー操作で変えられる範囲にする。地図を完全に隠さない
// よう上限は100vhにしない。
const MIN_SHEET_HEIGHT_VH = 20;
const MAX_SHEET_HEIGHT_VH = 80;
export const DEFAULT_SHEET_HEIGHT_VH = 50;
const HEIGHT_KEY_STEP_VH = 5;

export function clampSheetHeightVh(vh: number): number {
  return Math.min(MAX_SHEET_HEIGHT_VH, Math.max(MIN_SHEET_HEIGHT_VH, vh));
}

/** 中身がそのまま並んだときのシートの高さ。高さ指定を一時的に外して実測する——
 * `scrollHeight`は中身が箱より低いと箱の高さを返し、子要素の合算は中身側のflexが
 * 引き伸ばされている場合に箱の高さへ一致してしまうため、どちらも縮める判断に使えない。
 * 読み書きは同じレイアウト処理の中で完結するため、途中の高さが描画されることはない。 */
function naturalHeightOf(sheet: HTMLElement): number {
  const specified = sheet.style.height;
  sheet.style.height = "auto";
  const natural = sheet.getBoundingClientRect().height;
  sheet.style.height = specified;
  return natural;
}

// モバイル専用の部分高さシート（画面下部からせり上がる。高さの範囲は
// MIN_SHEET_HEIGHT_VH〜MAX_SHEET_HEIGHT_VH）。フルスクリーンの
// 暗幕は意図的に敷かない（シート表示中も上に見えている地図をパン/ズームできる状態を
// 保つ）。閉じる操作は✕ボタン・下スワイプ・呼び出し側のタブ再タップの3通り。シート外
// タップでは閉じない——地図をぐりぐり操作しながら凡例を見たい、というシート外のタップ・
// スクロール＝地図操作をシートを開いたまま自由にできるようにするため。
//
// 下スワイプでの閉じる判定（handleTouchStart/handleTouchEnd）はシート内のスクロールと
// 誤認しないよう、.body側でtouchイベントのbubbleを止める（下のJSX、.body要素の
// onTouchStart/onTouchEnd参照）。
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

  // 開いた時点の中身にちょうど合う高さへ合わせる。シートが中身より高いと、そのぶん地図が
  // 隠れたまま空白を見せることになる（設計原則「地図表示エリアを最大限確保する」）。
  // **開いている間は合わせ直さない**——候補の切り替え・区間クリックのたびに地図の見える
  // 範囲が動くと、地図を見ながらの操作が落ち着かないため。例外はfitKeyが変わったときだけで、
  // これは利用者自身が別の内容へ移った合図として扱う。
  // **利用者が自分で高さを決めた後（autoFitHeight=false）は一切合わせない**——決めた高さが
  // 中身の都合で戻ると、地図を広く見るために低くしておくことができない。
  // レイアウトを持たない実行（実寸が取れない環境）では何もしない——シート自身の高さが
  // 0のときはヘッダ・ハンドルぶんの差分も求まらず、合わせる先が出せない。
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
  // ハンドルの縦ドラッグによる高さ変更。ドラッグ開始時点の高さを起点に、指の移動量(vh換算)を
  // 足し込む。pointerIdで対象を絞るのは、まれに複数指が絡んだ場合に別指のmove/upで誤反応
  // しないようにするため。
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
    // 縦方向の下スワイプのみ閉じる対象にする（横方向の動きが大きい場合はシート内の
    // 横スクロール要素の操作とみなして無視する。page.tsx旧ドロワーの左スワイプ判定と同じ考え方）
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
    // 上方向のドラッグ（clientYが減る）で高さが増えるよう符号を反転する
    const deltaVh = ((drag.startClientY - e.clientY) / window.innerHeight) * 100;
    onHeightChange(clampSheetHeightVh(drag.startHeightVh + deltaVh));
  }

  function handleHandlePointerUp(e: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || e.pointerId !== drag.pointerId) return;
    dragRef.current = null;
    onHeightCommit(heightVh);
  }

  // タッチデバイスではpointerdownと別にネイティブのtouchstartも.handleからバブルするため、
  // 何もしないとsheet側のonTouchStart（上のhandleTouchStart、下スワイプで閉じる判定）が
  // ハンドル操作の開始点としても記録されてしまい、ドラッグ後の指離しが誤って閉じる判定に
  // 巻き込まれることがある。ハンドル上のtouchstartはバブルを止めて競合を避ける。
  function handleHandleTouchStart(e: React.TouchEvent) {
    e.stopPropagation();
  }

  function handleHandleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "ArrowUp") {
      e.preventDefault();
      const next = clampSheetHeightVh(heightVh + HEIGHT_KEY_STEP_VH);
      onHeightChange(next);
      onHeightCommit(next);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = clampSheetHeightVh(heightVh - HEIGHT_KEY_STEP_VH);
      onHeightChange(next);
      onHeightCommit(next);
    }
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
        onTouchStart={handleHandleTouchStart}
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
      {/* シート内容のスクロールがシート全体の下スワイプ判定（handleTouchStart/
          handleTouchEnd）まで届かないよう、ここでbubbleを止める。止めないと、
          スクロールで指を大きく動かしただけで「下スワイプで閉じる」と誤認されてしまう。 */}
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
