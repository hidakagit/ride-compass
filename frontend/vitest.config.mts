import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    // vitest既定のtestTimeout(5000ms)は、node_modules未インストール直後のコールドスタート
    // （Vite変換・jsdom環境セットアップに数十秒かかりうる、改善計画T125実測: 初回のenvironment
    // 39.56秒・transform 7.16秒）と競合し、実装は正しいのにテストがタイムアウトで落ちる偽陽性を
    // 生む（SafetyRecipePanel.test.tsx/TrafficStressRecipePanel.test.tsxの情報アイコン開閉テスト
    // 等で複数回再現）。コールドスタート実測（初回6.4秒）に十分な余裕を持たせた値へ引き上げる。
    testTimeout: 15000,
    // 改善計画T329: 既定のDOM環境をjsdomからhappy-domへ変更（テストスイート全体で
    // 30秒→19秒、約35%短縮を実測。環境構築コストだけでなくテスト本体の実行時間も
    // 縮む）。canvas.getContext("2d")が未実装でnullを返す挙動（windArrowIcon.ts/
    // routeArrowIcon.tsのフォールバック分岐が依存する）もjsdomと同一であることを
    // 確認済み。既定のjsdom環境を使う全テスト（下記の`@vitest-environment node`指定
    // ファイルを除く）が対象になる。個別ファイルで`// @vitest-environment jsdom`
    // docblockを付けば従来のjsdomへ戻せる（happy-domが特定APIで挙動差を持つ場合の
    // 逃げ道として）。`isolate: false`（ファイル間でモジュール状態・DOM環境を使い回す
    // 高速化）も試したが、テストが実行のたびに異なる4〜8件で不安定に失敗する
    // 副作用があり不採用（速度最適化はテストの検証内容を変えない範囲で行う、
    // docs/testing.md基本原則3）。
    environment: "happy-dom",
    // jsdom環境の構築はテストファイルごとに毎回発生し（vitestのデフォルトはファイル単位で
    // 環境を再構築する）、DOMを使わない純ロジックのテスト（services/lib/Map内の式・
    // フィルタ関数群）にまで一律で課すと無駄なオーバーヘッドになる（実測でsetup/environment
    // 込みのテスト全体の壁時計時間がテスト本体の実行時間よりずっと大きい要因の一つ）。
    // render/renderHook/window等のDOM APIを使わないファイルだけ軽量なnode環境に倒す。
    //
    // 当初この振り分けをtest.environmentMatchGlobsで一括指定していたが、インストール済み
    // vitest 4.1.10にはこのオプションが存在せず（Vitest 3系までのオプションで4系で廃止）、
    // `npx tsc --noEmit`がInlineConfig型エラーで落ちるだけでなくランタイムでも黙って
    // 無視されていた（`typeof window`をプローブして確認、全ファイルがjsdomのまま実行されて
    // おり最適化が機能していなかった）。Vitest 4での正しい代替はtest.projects（ワークスペース
    // 機能）だが、ファイル探索の単位自体が変わり対象パターンに含まれないテストファイルが
    // 静かに実行対象外になるリスクがあるため採用しなかった。代わりに、対象15ファイルそれぞれの
    // 先頭へ`// @vitest-environment node`docblock（バージョン間で仕様が安定している既存機構）を
    // 個別に付与する方式にした。新規ファイルは明示的にdocblockを足さない限り既定のjsdomのままな
    // ので、DOM依存を後から追加してもテストが静かに壊れることはない（環境振り分けの単一情報源が
    // 各ファイル自身になる）。
    setupFiles: ["./vitest.setup.ts"],
    css: true,
    // frontend/e2e/はPlaywright（別ランナー、npm run test:e2e）専用のため、
    // vitestのデフォルトテスト探索（*.spec.ts）から除外する。
    // .claude/worktrees/配下は並行セッションが一時的に作るgit worktree（他ブランチの
    // frontend/を丸ごと含む）で、配下に同名のtest.tsxが並存すると本セッションのnpm testが
    // 誤って拾ってしまい「document is not defined」等の偽陽性を大量発生させる実害が
    // 実機で確認された（設計レビュー横展開: 過去にe2e/**を除外したのと同じ「意図しない
    // ファイルを拾う」バグクラス）。configDefaults.excludeがnode_modules配下しか除外しないため
    // worktree自体を明示的に除外する。
    exclude: [...configDefaults.exclude, "e2e/**", "**/.claude/worktrees/**"],
  },
});
