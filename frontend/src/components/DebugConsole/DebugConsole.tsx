"use client";

import { useEffect, useRef } from "react";
import { useDebugEnabled, useDebugLogEntries } from "@/hooks/useDebugLog";
import { clearDebugLog } from "@/lib/debugLog";
import FloatingPanel from "@/components/FloatingPanel/FloatingPanel";
import styles from "./DebugConsole.module.css";

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
// バックエンドの集計・commit等の「システム状況」は別パネル（SystemStatusPanel）へ分離した
// （ログ本文と情報源・更新頻度が異なる別種の情報を1つのパネルに詰め込むと見づらいという
// ユーザーフィードバックを受け、2026-08-16に分割）。
export default function DebugConsole({ open, onClose }: DebugConsoleProps) {
  const enabled = useDebugEnabled();
  const entries = useDebugLogEntries();
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries]);

  if (!enabled) return null;

  return (
    <FloatingPanel
      open={open}
      onClose={onClose}
      title={`デバッグログ（${entries.length}件）`}
      topRem={4.25}
      widthRem={22}
      maxHeightPx={420}
      headerButtons={
        <button type="button" onClick={clearDebugLog} className={styles.clearButton}>
          クリア
        </button>
      }
    >
      <div ref={listRef} className={styles.entries}>
        {entries.length === 0 && <p className={styles.emptyMessage}>イベント待機中...（地図を操作するかAPIを呼び出してください）</p>}
        {entries.map((entry) => (
          <div key={entry.id} className={styles.entry} data-level={entry.level}>
            <span className={styles.entryTime}>{entry.time}</span> <span className={styles.entryCategory}>[{entry.category}]</span>{" "}
            <span className={styles.entryMessage}>{entry.message}</span>
            {entry.detail != null && <span className={styles.entryDetail}> {JSON.stringify(entry.detail)}</span>}
          </div>
        ))}
      </div>
    </FloatingPanel>
  );
}
