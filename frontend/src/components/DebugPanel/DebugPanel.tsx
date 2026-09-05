"use client";

import { useDebugEnabled } from "@/hooks/useDebugLog";
import { setDebugEnabled } from "@/lib/debugLog";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";

// サイドバーに置く小さなトグル。オンにすると地図イベント・外部API呼び出しの詳細ログを
// 画面下部のDebugConsoleとブラウザコンソールの両方に出す（services/配下のfetchラッパー、
// MapView.tsxのmapイベントハンドラから呼ばれるdebugLog()を参照）。
// ログ表示専任（研究機能の出し入れはResearchPanel）。
export default function DebugPanel() {
  const enabled = useDebugEnabled();

  return (
    <label className="flex items-center gap-[0.3rem] text-[length:var(--font-size-md)]">
      <Checkbox checked={enabled} onCheckedChange={setDebugEnabled} aria-label="デバッグログを表示" />
      デバッグログを表示
    </label>
  );
}
