"use client";

import { useEffect, useRef } from "react";
import styles from "./BottomSheet.module.css";

interface BottomSheetProps {
  open: boolean;
  onClose: () => void;
  /** シートの見出し（アクセシブル名にも使う） */
  title: string;
  /** 見出しのDOM id。地図上の条件サマリ等、外部からこのシートの中身へフォーカスを送る
   *起点として使うことがある（page.tsxのhandleLayerSummaryClick参照）。 */
  titleId: string;
  children: React.ReactNode;
}

const SWIPE_CLOSE_THRESHOLD_PX = 60;

// モバイル専用の部分高さシート（画面下部から最大70%程度せり上がる）。
// モバイル実機フィードバック対応T34: 「サイドバーで設定をいじっている間、地図を直接
// 確認できない」という実機フィードバックを受け、全面ドロワー＋暗幕だった旧UIを置き換える。
// フルスクリーンの暗幕は意図的に敷かない（シート表示中も上に見えている地図をパン/ズーム
// できる状態を保つ）。閉じる操作は✕ボタン・下スワイプ・呼び出し側のタブ再タップの3通り
// （タップアウトでは閉じない。地図操作と閉じる操作が競合しないようにするため、
// page.tsxの旧ドロワーが持っていた暗幕クリックでの閉じるロジックはここでは採用しない）。
export default function BottomSheet({ open, onClose, title, titleId, children }: BottomSheetProps) {
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);

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

  return (
    // app-bottom-sheetはglobals.css側のモバイル向けタップ領域ルール
    // （.app-sidebar button, .app-bottom-sheet button等）が参照するグローバルなマーカー
    // クラス。CSS Modulesのクラス名はハッシュ化されグローバルCSSから参照できないため、
    // 見た目自体はstyles.sheetに任せつつ、このマーカークラスだけ併用している
    // （DebugConsoleの.app-debug-consoleと同じ手法）。
    <div
      className={`${styles.sheet} app-bottom-sheet`}
      role="dialog"
      aria-labelledby={titleId}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      <div className={styles.handle} aria-hidden="true" />
      <div className={styles.header}>
        <h2 id={titleId} tabIndex={-1} className={styles.title}>
          {title}
        </h2>
        <button type="button" onClick={onClose} aria-label="閉じる" className={styles.closeButton}>
          ✕
        </button>
      </div>
      <div className={styles.body}>{children}</div>
    </div>
  );
}
