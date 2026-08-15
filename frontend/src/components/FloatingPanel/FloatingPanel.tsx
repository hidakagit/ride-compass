"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import styles from "./FloatingPanel.module.css";

interface FloatingPanelProps {
  /** パネル自体の開閉。呼び出し側（DebugConsole/SystemStatusPanel）が個別に持つ状態 */
  open: boolean;
  onClose: () => void;
  title: string;
  /** ヘッダーの閉じるボタンより前に置く追加ボタン（クリア・更新など、パネルごとに異なる） */
  headerButtons?: ReactNode;
  children: ReactNode;
  /** 既定の上端位置（rem）。天候ヘッダの下から始まる高さに揃えるため既定4.25 */
  topRem?: number;
  /** 既定の幅（rem） */
  widthRem?: number;
  /** 本文の最大高さ（px）。これを超える分はbody内でスクロールする */
  maxHeightPx?: number;
}

// 一般ユーザーは使わない開発者向けパネル（デバッグログ・システム状況）の共通シェル。
// サイドバー/地図に場所を固定せず、ビューポート基準で浮かせた独立パネルにする
// （「設定」内のボタンから開閉、T43）。位置はヘッダーのつまみをドラッグして動かせる。
// 2パネルとも同じ挙動（ドラッグ・既定位置リセット・半透明の暗い配色）を必要としたため、
// DebugConsole単体だった実装をここへ切り出した（システム状況パネルの新設に伴う共通化）。
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
  const dragRef = useRef<{ pointerId: number; startClientX: number; startClientY: number; startLeft: number; startTop: number } | null>(
    null,
  );
  // null=既定位置（画面上部中央寄せ、topRem/widthRemで決まる）。ドラッグすると具体的な
  // top/leftへ切り替える。
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  // 開き直すたびに既定位置へ戻す。ドラッグ位置は開いている間だけの一時的な配置という
  // 位置づけ（永続化はしない）。effect本体からの直接同期setState呼び出しを避け、
  // マイクロタスク経由で実行する（react-hooks/set-state-in-effect対策）。
  useEffect(() => {
    if (open) Promise.resolve().then(() => setPosition(null));
  }, [open]);

  if (!open) return null;

  function handleDragHandlePointerDown(e: React.PointerEvent<HTMLDivElement>) {
    const rect = panelRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragRef.current = {
      pointerId: e.pointerId,
      startClientX: e.clientX,
      startClientY: e.clientY,
      startLeft: rect.left,
      startTop: rect.top,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function handleDragHandlePointerMove(e: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || e.pointerId !== drag.pointerId) return;
    setPosition({
      left: drag.startLeft + (e.clientX - drag.startClientX),
      top: drag.startTop + (e.clientY - drag.startClientY),
    });
  }

  function handleDragHandlePointerUp(e: React.PointerEvent<HTMLDivElement>) {
    if (dragRef.current?.pointerId === e.pointerId) dragRef.current = null;
  }

  return (
    // app-floating-panelはglobals.css側のモバイル向けタップ領域ルール
    // （.app-sidebar button, .app-floating-panel button）が参照するグローバルなマーカー
    // クラス。CSS Modulesのクラス名はハッシュ化されグローバルCSSから参照できないため、
    // 見た目自体はstyles.panelに任せつつ、このマーカークラスだけ併用している。
    <div
      ref={panelRef}
      className={`${styles.panel} app-floating-panel`}
      style={{
        width: `min(${widthRem}rem, calc(100vw - 2 * var(--space-3)))`,
        maxHeight: `${maxHeightPx}px`,
        // ドラッグ中はCSSの既定の左右中央寄せ（transform: translateX(-50%)）を打ち消し、
        // top/leftをそのまま画面座標として使う（打ち消さないと中央寄せ分だけ位置がずれる）。
        ...(position != null
          ? { top: `${position.top}px`, left: `${position.left}px`, transform: "none" }
          : { top: `${topRem}rem` }),
      }}
    >
      <div className={styles.header}>
        <div
          className={styles.dragHandle}
          onPointerDown={handleDragHandlePointerDown}
          onPointerMove={handleDragHandlePointerMove}
          onPointerUp={handleDragHandlePointerUp}
          role="separator"
          aria-label="ドラッグしてパネルを移動"
          title="ドラッグして移動"
        >
          ⠿
        </div>
        <strong className={styles.title}>{title}</strong>
        <div className={styles.headerButtons}>
          {headerButtons}
          <button type="button" onClick={onClose} aria-label={`${title}を閉じる`} className={styles.closeButton}>
            ✕
          </button>
        </div>
      </div>
      <div className={styles.body}>{children}</div>
    </div>
  );
}
