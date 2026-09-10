"use client";

// error.tsxはルートレイアウト自体のレンダリングエラーは捕捉できない
// （layout.tsxの外側を置き換えるため、独自のhtml/bodyタグが必要）。
// この最外殻が無いと、レイアウト自体が壊れた場合に完全な白画面になる。
//
// **色はトークン（var(--color-muted)等）を使わず直値で書く**。layout.tsxごと置き換わる
// ため`globals.css`が読み込まれておらず、トークンは未定義＝色指定が丸ごと無効になる
// （error.tsxはlayout配下なのでトークンを使える）。
export default function GlobalError({
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <html lang="ja">
      <body>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            height: "100vh",
            gap: "1rem",
            padding: "1rem",
            textAlign: "center",
          }}
        >
          <h2>アプリの読み込み中にエラーが発生しました</h2>
          <p style={{ color: "#666" }}>ページを再読み込みしてください。</p>
          <button onClick={() => retry()} style={{ padding: "0.5rem 1rem" }}>
            再試行
          </button>
        </div>
      </body>
    </html>
  );
}
