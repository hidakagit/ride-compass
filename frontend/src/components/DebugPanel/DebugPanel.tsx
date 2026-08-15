"use client";

import { useDebugEnabled } from "@/hooks/useDebugLog";
import { setDebugEnabled } from "@/lib/debugLog";
import styles from "./DebugPanel.module.css";

// サイドバーに置く小さなトグル。オンにすると地図イベント・外部API呼び出しの詳細ログを
// 画面下部のDebugConsoleとブラウザコンソールの両方に出す（services/配下のfetchラッパー、
// MapView.tsxのmapイベントハンドラから呼ばれるdebugLog()を参照）。
// ログ表示専任（研究機能の出し入れはResearchPanel。改善計画T29の2役分割）。
export default function DebugPanel() {
  const enabled = useDebugEnabled();

  return (
    <label className={styles.label}>
      <input type="checkbox" checked={enabled} onChange={(e) => setDebugEnabled(e.target.checked)} />
      デバッグログを表示
    </label>
  );
}
