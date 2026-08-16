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
    environment: "jsdom",
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
