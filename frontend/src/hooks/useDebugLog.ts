"use client";

import { useSyncExternalStore } from "react";
import type { DebugLogEntry } from "@/lib/debugLog";
import { getDebugLogEntries, isDebugEnabled, subscribeDebugLog } from "@/lib/debugLog";

// getServerSnapshotは呼ばれるたびに同じ参照を返す必要がある（毎回新しい配列/関数を
// 返すとReactが「値が変わり続けている」と判断し無限ループ警告になる）。
const SERVER_SNAPSHOT_ENTRIES: DebugLogEntry[] = [];

export function useDebugEnabled(): boolean {
  return useSyncExternalStore(subscribeDebugLog, isDebugEnabled, () => false);
}

export function useDebugLogEntries(): DebugLogEntry[] {
  return useSyncExternalStore(subscribeDebugLog, getDebugLogEntries, () => SERVER_SNAPSHOT_ENTRIES);
}
