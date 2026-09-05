"use client";

import { useEffect, useRef } from "react";
import styles from "./BottomSheet.module.css";

interface BottomSheetProps {
  open: boolean;
  onClose: () => void;
  /** シートの見出し（アクセシブル名にも使う） */
  title: string;
  /** 見出しのDOM id。外部からこのシートの中身へフォーカスを送る起点として使うことがある
   *（page.tsxのhandleGoToGenerate参照）。 */
  titleId: string;
  /** ヘッダ右側、閉じるボタンの手前へ差し込む任意の要素。シートごとの補足説明の
   * 情報アイコン・アクションボタンをヘッダ右上へ集約するための差し込み口（page.tsx:
   * 「ルート結果」シートのrenderRouteResultHeaderActions参照）。 */
  headerAction?: React.ReactNode;
  children: React.ReactNode;
  /** シートの高さ（vh）。「ルートを作る」「地図の見え方」の2シートは排他表示のため、
   * 呼び出し側（page.tsx）が1つの値を共有して持ち、どちらを開いても直前の高さを保つ。 */
  heightVh: number;
  /** ドラッグ・キー操作の途中も含めて随時呼ばれる（見た目の即時反映用）。 */
  onHeightChange: (vh: number) => void;
  /** ドラッグ終了・キー操作確定時にのみ呼ばれる（永続化用。ドラッグ中の連続書き込みを避ける）。 */
  onHeightCommit: (vh: number) => void;
}

const SWIPE_CLOSE_THRESHOLD_PX = 60;

// 「ちょうどいい高さ」はユーザーによって違う（片手操作か両手か、地図をどれだけ見たいか等）
// ため固定値にせず、ハンドルドラッグ/キー操作で変えられる範囲にする。地図を完全に隠さない
// よう上限は100vhにしない。
export const MIN_SHEET_HEIGHT_VH = 20;
export const MAX_SHEET_HEIGHT_VH = 80;
export const DEFAULT_SHEET_HEIGHT_VH = 50;
const HEIGHT_KEY_STEP_VH = 5;

export function clampSheetHeightVh(vh: number): number {
  return Math.min(MAX_SHEET_HEIGHT_VH, Math.max(MIN_SHEET_HEIGHT_VH, vh));
}

// モバイル専用の部分高さシート（画面下部から最大70%程度せり上がる）。フルスクリーンの
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
  children,
  heightVh,
  onHeightChange,
  onHeightCommit,
}: BottomSheetProps) {
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);
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
    // app-bottom-sheetはglobals.css側のモバイル向けタップ領域ルール
    // （.app-sidebar button, .app-bottom-sheet button等）が参照するグローバルなマーカー
    // クラス。CSS Modulesのクラス名はハッシュ化されグローバルCSSから参照できないため、
    // 見た目自体はstyles.sheetに任せつつ、このマーカークラスだけ併用している
    // （FloatingPanelの.app-floating-panelと同じ手法）。
    <div
      className={`${styles.sheet} app-bottom-sheet`}
      role="dialog"
      aria-labelledby={titleId}
      style={{ height: `${heightVh}vh` }}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      <div
        className={styles.handle}
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
      <div className={styles.header}>
        <h2 id={titleId} tabIndex={-1} className={styles.title}>
          {title}
        </h2>
        <div className={styles.headerActions}>
          {headerAction}
          <button type="button" onClick={onClose} aria-label="閉じる" className={styles.closeButton}>
            ✕
          </button>
        </div>
      </div>
      {/* シート内容のスクロールがシート全体の下スワイプ判定（handleTouchStart/
          handleTouchEnd）まで届かないよう、ここでbubbleを止める。止めないと、
          スクロールで指を大きく動かしただけで「下スワイプで閉じる」と誤認されてしまう。 */}
      <div className={styles.body} onTouchStart={(e) => e.stopPropagation()} onTouchEnd={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}
