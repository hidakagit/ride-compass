// 調査用デバッグモード。マップ表示イベント・外部API呼び出しをイベント単位でログする。
// フレームワーク非依存のシングルトンとして持つことで、Reactコンポーネントだけでなく
// services/配下のfetchラッパーやMapView.tsxのmapイベントハンドラからも直接呼べるようにする。

export type DebugLogLevel = "info" | "warn" | "error";

export interface DebugLogEntry {
  id: number;
  time: string;
  category: string;
  message: string;
  detail?: unknown;
  level: DebugLogLevel;
}

const STORAGE_KEY = "ridecompass:debug-enabled";
const MAX_ENTRIES = 300;

let enabled = typeof window !== "undefined" && window.localStorage.getItem(STORAGE_KEY) === "1";
let entries: DebugLogEntry[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

export function isDebugEnabled(): boolean {
  return enabled;
}

export function setDebugEnabled(next: boolean): void {
  enabled = next;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
  }
  notify();
}

export function getDebugLogEntries(): DebugLogEntry[] {
  return entries;
}

export function clearDebugLog(): void {
  entries = [];
  notify();
}

export function subscribeDebugLog(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function formatTime(date: Date): string {
  return `${date.toTimeString().slice(0, 8)}.${String(date.getMilliseconds()).padStart(3, "0")}`;
}

export function debugLog(category: string, message: string, detail?: unknown, level: DebugLogLevel = "info"): void {
  if (!enabled) return;
  const entry: DebugLogEntry = { id: nextId++, time: formatTime(new Date()), category, message, detail, level };
  entries = [...entries, entry].slice(-MAX_ENTRIES);
  const consoleFn = level === "error" ? console.error : level === "warn" ? console.warn : console.debug;
  consoleFn(`[RideCompass Debug] [${category}] ${message}`, detail ?? "");
  notify();
}
