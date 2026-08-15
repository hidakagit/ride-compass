"use client";

import { useEffect, useRef, useState } from "react";
import { useDebugEnabled, useDebugLogEntries } from "@/hooks/useDebugLog";
import { clearDebugLog } from "@/lib/debugLog";
import styles from "./DebugConsole.module.css";

// DebugConsole.module.cssの.consoleが持つmax-heightと一致させること。
export const DEBUG_CONSOLE_MAX_HEIGHT_PX = 220;

interface DebugConsoleProps {
  /** パネル自体の開閉（デバッグモードのON/OFFとは別。常時占有させたくないという実機
   * フィードバックを受け、「設定」内のボタンから開閉する、T42） */
  open: boolean;
  onClose: () => void;
}

// デバッグモードON時のみ、地図の上に浮かべて表示するイベントログ。
// マップの表示イベント（初期化・タイル/スタイル要求・パン/ズーム）と外部API呼び出し
// （天候/ルート生成/地域レイヤー/基礎地図）を発生順に積む。DebugPanelのトグルと状態を共有する。
// デバッグモードON＝ログの記録自体は常時有効だが、このパネル表示は別途openで制御する
// （常時ONだと画面の目立つ面積を占有し続けるという実機フィードバック、T42）。
// 一般ユーザーは使わない機能のため、サイドバー/地図に固定するのではなく、ヘッダーの
// つまみでドラッグして動かせる・地図を透かして見られる独立したフローティングパネルにした
// （地図上アイコン列からの分離、モバイル実機フィードバック対応T43）。
export default function DebugConsole({ open, onClose }: DebugConsoleProps) {
  const enabled = useDebugEnabled();
  const entries = useDebugLogEntries();
  const listRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ pointerId: number; startClientX: number; startClientY: number; startLeft: number; startTop: number } | null>(
    null,
  );
  // null=CSSの既定位置（画面中央）。ドラッグすると具体的なtop/leftへ切り替える。
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries]);

  // 開き直すたびに既定位置（画面中央）へ戻す。ドラッグ位置は開いている間だけの一時的な
  // 配置という位置づけ（永続化はしない）。effect本体からの直接同期setState呼び出しを避け、
  // マイクロタスク経由で実行する（react-hooks/set-state-in-effect対策、page.tsxの
  // fetchWeatherForと同じ流儀）。
  useEffect(() => {
    if (open) Promise.resolve().then(() => setPosition(null));
  }, [open]);

  if (!enabled || !open) return null;

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
    // app-debug-consoleはglobals.css側のモバイル向けタップ領域ルール
    // （.app-sidebar button, .app-debug-console button）が参照するグローバルなマーカー
    // クラス。CSS Modulesのクラス名はハッシュ化されグローバルCSSから参照できないため、
    // 見た目自体はstyles.consoleに任せつつ、このマーカークラスだけ併用している。
    <div
      ref={panelRef}
      className={`${styles.console} app-debug-console`}
      // ドラッグ中はCSSの既定中央寄せ（transform: translate(-50%, -50%)）を打ち消し、
      // top/leftをそのまま画面座標として使う（打ち消さないと中央寄せ分だけ位置がずれる）。
      style={
        position != null ? { top: `${position.top}px`, left: `${position.left}px`, transform: "none" } : undefined
      }
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
        <strong className={styles.title}>デバッグログ（{entries.length}件）</strong>
        <div className={styles.headerButtons}>
          <button type="button" onClick={clearDebugLog} className={styles.clearButton}>
            クリア
          </button>
          <button type="button" onClick={onClose} aria-label="デバッグログを閉じる" className={styles.closeButton}>
            ✕
          </button>
        </div>
      </div>
      <div ref={listRef} className={styles.entries}>
        {entries.length === 0 && <p className={styles.emptyMessage}>イベント待機中...（地図を操作するかAPIを呼び出してください）</p>}
        {entries.map((entry) => (
          <div key={entry.id} className={styles.entry}>
            <span className={styles.entryTime}>{entry.time}</span> <span className={styles.entryCategory}>[{entry.category}]</span>{" "}
            {entry.message}
            {entry.detail != null && <span className={styles.entryDetail}> {JSON.stringify(entry.detail)}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
