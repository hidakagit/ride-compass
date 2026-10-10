"use client";

import { useDebugEnabled } from "@/hooks/useDebugLog";
import { setDebugEnabled } from "@/lib/debugLog";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";

// 管理画面に置く小さなトグル。オンにすると地図イベント・外部API呼び出しの詳細ログを
// DebugConsole（地図の画面のメニューから開く）とブラウザコンソールの両方に出す（`lib/debugLog.ts`）。
export default function DebugPanel() {
  const enabled = useDebugEnabled();

  return (
    <label className="flex items-center gap-[0.3rem] text-[length:var(--font-size-md)]">
      <Checkbox checked={enabled} onCheckedChange={setDebugEnabled} aria-label="デバッグログを表示" />
      デバッグログを表示
    </label>
  );
}
