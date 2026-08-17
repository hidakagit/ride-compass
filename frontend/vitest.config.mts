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
    environment: "jsdom",
    // jsdom環境の構築はテストファイルごとに毎回発生し（vitestのデフォルトはファイル単位で
    // 環境を再構築する）、DOMを使わない純ロジックのテスト（services/lib/Map内の式・
    // フィルタ関数群）にまで一律で課すと無駄なオーバーヘッドになる（実測でsetup/environment
    // 込みのテスト全体の壁時計時間がテスト本体の実行時間よりずっと大きい要因の一つ）。
    // render/renderHook/window等のDOM APIを使わないファイルだけ軽量なnode環境に倒す。
    // 新規ファイルは明示的にここへ加えない限りデフォルトのjsdomのままなので、
    // DOM依存を後から追加してもテストが静かに壊れることはない。
    environmentMatchGlobs: [
      ["src/services/regionApi.test.ts", "jsdom"], // window.location.originを直接参照する
      ["src/services/**", "node"],
      ["src/lib/apiError.test.ts", "node"],
      ["src/components/Map/*.test.ts", "node"], // .tsxのコンポーネントテストは対象外（拡張子で区別）
      ["src/app/api/**", "node"],
    ],
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
