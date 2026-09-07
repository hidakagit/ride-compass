// localStorageの読み書きのうち、失敗を呼び出し側で握りつぶせない場所のための薄いラッパ。
//
// サイトデータを全面的にブロックしている環境では`window.localStorage`のゲッター自体が
// SecurityErrorを投げる。モジュール評価時（importの連鎖の途中）の読み出しがこれを浴びると
// 例外を受け止める場所が無く、そのモジュールを読むページ全体が描画されない。
//
// コンポーネント内の永続化はhooks/useStoredState.tsが同じ失敗を状態のフォールバックとして
// 扱う。こちらはReactの外（モジュール評価時に初期値を決めるシングルトン）向け。

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
