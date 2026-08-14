"use client";

import { useEffect, useRef } from "react";
import { useDebugEnabled, useDebugLogEntries } from "@/hooks/useDebugLog";
import { clearDebugLog } from "@/lib/debugLog";
import styles from "./DebugConsole.module.css";

// DebugConsole.module.cssの.consoleが持つmax-heightと一致させること。地図右下の
// 「現在地に移動」ボタン（page.tsx）が、デバッグモード表示中はこのパネルと重ならないよう
// 位置を計算する際にも参照する。
export const DEBUG_CONSOLE_MAX_HEIGHT_PX = 220;

// デバッグモードON時のみ、地図コンテナの下端に重ねて表示するイベントログ。
// マップの表示イベント（初期化・タイル/スタイル要求・パン/ズーム）と外部API呼び出し
// （天候/ルート生成/地域レイヤー/基礎地図）を発生順に積む。DebugPanelのトグルと状態を共有する。
export default function DebugConsole() {
  const enabled = useDebugEnabled();
  const entries = useDebugLogEntries();
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries]);

  if (!enabled) return null;

  return (
    // app-debug-consoleはglobals.css側のモバイル向けタップ領域ルール
    // （.app-sidebar button, .app-debug-console button）が参照するグローバルなマーカー
    // クラス。CSS Modulesのクラス名はハッシュ化されグローバルCSSから参照できないため、
    // 見た目自体はstyles.consoleに任せつつ、このマーカークラスだけ併用している。
    <div className={`${styles.console} app-debug-console`}>
      <div className={styles.header}>
        <strong>デバッグログ（{entries.length}件）</strong>
        <button type="button" onClick={clearDebugLog} className={styles.clearButton}>
          クリア
        </button>
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
