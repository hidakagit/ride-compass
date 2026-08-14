"use client";

import { useEffect, useRef } from "react";
import { useDebugEnabled, useDebugLogEntries } from "@/hooks/useDebugLog";
import { clearDebugLog } from "@/lib/debugLog";

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
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 0,
        maxHeight: "220px",
        display: "flex",
        flexDirection: "column",
        background: "rgba(17,24,39,0.92)",
        color: "#e5e7eb",
        fontFamily: "monospace",
        fontSize: "0.75rem",
        zIndex: 10,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "0.3rem 0.5rem",
          borderBottom: "1px solid rgba(255,255,255,0.15)",
        }}
      >
        <strong>デバッグログ（{entries.length}件）</strong>
        <button type="button" onClick={clearDebugLog} style={{ fontSize: "0.7rem" }}>
          クリア
        </button>
      </div>
      <div ref={listRef} style={{ overflowY: "auto", padding: "0.3rem 0.5rem" }}>
        {entries.length === 0 && <p style={{ color: "#9ca3af" }}>イベント待機中...（地図を操作するかAPIを呼び出してください）</p>}
        {entries.map((entry) => (
          <div key={entry.id} style={{ borderBottom: "1px solid rgba(255,255,255,0.08)", padding: "0.1rem 0" }}>
            <span style={{ color: "#9ca3af" }}>{entry.time}</span> <span style={{ color: "#60a5fa" }}>[{entry.category}]</span>{" "}
            {entry.message}
            {entry.detail != null && <span style={{ color: "#9ca3af" }}> {JSON.stringify(entry.detail)}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
