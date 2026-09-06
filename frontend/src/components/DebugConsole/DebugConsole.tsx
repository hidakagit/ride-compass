"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useDebugEnabled, useDebugLogEntries } from "@/hooks/useDebugLog";
import { clearDebugLog, type DebugLogLevel } from "@/lib/debugLog";
import FloatingPanel from "@/components/FloatingPanel/FloatingPanel";
import styles from "./DebugConsole.module.css";

interface DebugConsoleProps {
  /** パネル自体の開閉（デバッグモードのON/OFFとは別。常時占有させたくないため
   * 「設定」内のボタンから開閉する） */
  open: boolean;
  onClose: () => void;
}

// info < warn < error の順で「この段階以上だけ表示」というしきい値フィルタにする
// （個別レベルのON/OFFではなく段階選択にすることで、選択肢を3つの<select>に収める）。
const LEVEL_ORDER: readonly DebugLogLevel[] = ["info", "warn", "error"];

// デバッグモードON時のみ、地図の上に浮かべて表示するイベントログ。
// マップの表示イベント（初期化・タイル/スタイル要求・パン/ズーム）と外部API呼び出し
// （天候/ルート生成/地域レイヤー/基礎地図）を発生順に積む。DebugPanelのトグルと状態を共有する。
// デバッグモードON＝ログの記録自体は常時有効だが、このパネル表示は別途openで制御する
// （常時ONだと画面の目立つ面積を占有し続けるため）。
// バックエンドの集計・commit等の「システム状況」は別パネル（SystemStatusPanel）へ
// 分離してある（ログ本文と情報源・更新頻度が異なる別種の情報を1つのパネルに詰め込むと
// 見づらいため）。
export default function DebugConsole({ open, onClose }: DebugConsoleProps) {
  const enabled = useDebugEnabled();
  const entries = useDebugLogEntries();
  const listRef = useRef<HTMLDivElement>(null);
  const [minLevel, setMinLevel] = useState<DebugLogLevel>("info");

  const visibleEntries = useMemo(
    () => entries.filter((entry) => LEVEL_ORDER.indexOf(entry.level) >= LEVEL_ORDER.indexOf(minLevel)),
    [entries, minLevel]
  );

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [visibleEntries]);

  if (!enabled) return null;

  return (
    <FloatingPanel
      open={open}
      onClose={onClose}
      title={`デバッグログ[${visibleEntries.length}/${entries.length}件]`}
      topRem={4.25}
      widthRem={22}
      maxHeightPx={420}
      headerButtons={
        <>
          <select
            value={minLevel}
            onChange={(e) => setMinLevel(e.target.value as DebugLogLevel)}
            className={styles.levelSelect}
            aria-label="表示するログレベルの下限"
          >
            <option value="info">すべて</option>
            <option value="warn">警告以上</option>
            <option value="error">エラーのみ</option>
          </select>
          <button type="button" onClick={clearDebugLog} className={styles.clearButton}>
            クリア
          </button>
        </>
      }
    >
      <div ref={listRef} className={styles.entries}>
        {entries.length === 0 && <p className={styles.emptyMessage}>イベント待機中...[地図を操作するかAPIを呼び出してください]</p>}
        {entries.length > 0 && visibleEntries.length === 0 && (
          <p className={styles.emptyMessage}>条件に一致するログがありません[フィルタを「すべて」に戻すと{entries.length}件表示されます]</p>
        )}
        {visibleEntries.map((entry) => (
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
