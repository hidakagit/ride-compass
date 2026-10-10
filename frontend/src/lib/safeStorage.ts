// localStorageの読み書きの失敗を、呼び出し側へ投げない薄いラッパ。
//
// サイトデータを全面的にブロックしている環境では`window.localStorage`のゲッター自体が
// SecurityErrorを投げるので、`getItem`/`setItem`だけでなくゲッターも囲む。

/** localStorageの値を読む。使えない環境ではnullを返す（未保存と同じ扱い）。 */
export function readStoredValue(key: string): string | null {
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** localStorageへ書く。使えない環境では黙って捨てる（このセッション内の値は有効なまま）。 */
export function writeStoredValue(key: string, value: string): void {
  try {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(key, value);
  } catch {
    // 保存不可は無視（次回訪問時に既定値へ戻るだけ）
  }
}
