// 研究モード（評価重みの上書き・実験スロット・比較表）の有効フラグ。
// 以前はデバッグモード（lib/debugLog.ts）が「ログ表示」と「研究機能の出し入れ」の2役を
// 兼ねていたが、「ログを見たいだけなのに実験スロットが溜まる」「重みを試したいだけなのに
// コンソールが出る」という絡みを解くため独立させた（改善計画T29）。
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
