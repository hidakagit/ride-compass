"use client";

import { useDebugEnabled } from "@/hooks/useDebugLog";
import { setDebugEnabled } from "@/lib/debugLog";

// サイドバーに置く小さなトグル。オンにすると地図イベント・外部API呼び出しの詳細ログを
// 画面下部のDebugConsoleとブラウザコンソールの両方に出す（services/配下のfetchラッパー、
// MapView.tsxのmapイベントハンドラから呼ばれるdebugLog()を参照）。
export default function DebugPanel() {
  const enabled = useDebugEnabled();

  return (
    <label style={{ display: "flex", alignItems: "center", gap: "0.3rem", fontSize: "0.85rem" }}>
      <input type="checkbox" checked={enabled} onChange={(e) => setDebugEnabled(e.target.checked)} />
      デバッグモード（イベントログ）
    </label>
  );
}
