"use client";

import { useEffect } from "react";

// Reactのレンダリング時例外はError Boundaryが無いとアプリ全体が白画面になる
// （WeatherPanel/MapView等のnull未ガード箇所を踏んだ場合の最終防衛線）。App Routerの
// error.tsxはルートセグメント配下のレンダリングエラーをここで捕捉し、フォールバックUIを
// 表示する。
export default function Error({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
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
      <h2>予期しないエラーが発生しました</h2>
      <p style={{ color: "#666" }}>
        画面の表示中に問題が発生しました。再試行しても解決しない場合は、ページを再読み込みしてください。
      </p>
      <button onClick={() => retry()} style={{ padding: "0.5rem 1rem" }}>
        再試行
      </button>
    </div>
  );
}
