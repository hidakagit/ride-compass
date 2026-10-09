import { errorName, reportError } from "@/lib/errorReport";

// 画面が動き出す前に1度だけ読まれる（Next.jsのファイルの決まり）。どの部品も捕まえなかった例外とPromiseの拒否を報告する。
// 描画の例外はエラーの境界（`app/error.tsx`・`app/global-error.tsx`）が捕まえ、ここへは来ない。
window.addEventListener("error", (event) => reportError("exception", errorName(event.error)));
window.addEventListener("unhandledrejection", (event) => reportError("rejection", errorName(event.reason)));
