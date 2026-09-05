// 研究モード（評価重みの上書き・実験スロット・比較表）の有効フラグ。デバッグモード
// （lib/debugLog.ts、「ログ表示」専任）とは独立させてある——両者を1つのフラグで
// 兼ねると、「ログを見たいだけなのに実験スロットが溜まる」「重みを試したいだけなのに
// コンソールが出る」という絡みが生まれるため。
// シングルトン＋購読の形はdebugLog.tsと同じ（useSyncExternalStoreから使う）。

const STORAGE_KEY = "ridecompass:research-enabled";

let enabled = typeof window !== "undefined" && window.localStorage.getItem(STORAGE_KEY) === "1";
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

export function isResearchEnabled(): boolean {
  return enabled;
}

export function setResearchEnabled(next: boolean): void {
  enabled = next;
  if (typeof window !== "undefined") {
    // プライベートブラウジング等で保存できなくても、このセッション内の有効化は成立させる
    try {
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    } catch {
      // 保存不可は無視（次回訪問時に既定OFFへ戻るだけ）
    }
  }
  notify();
}

export function subscribeResearchMode(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
