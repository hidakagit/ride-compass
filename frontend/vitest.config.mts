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
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});
