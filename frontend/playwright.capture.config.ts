import { defineConfig } from "@playwright/test";
import { CHROMIUM_PROJECTS, standaloneServer } from "./playwright.config";

// 画面を撮る段（frontend/capture/）。テストではなく、CI にも載せない。入口と引数は scripts/capture.mjs が持ち、宛先を環境変数で
// 渡す: CAPTURE_BASE_URL（撮る画面のオリジン）と、手元のビルドを撮るときの CAPTURE_LOCAL_PORT・CAPTURE_SERVER_DIR（ビルドのある frontend）。

const localPort = process.env.CAPTURE_LOCAL_PORT;

export default defineConfig({
  testDir: "./capture",
  workers: 1,
  retries: 0,
  // 地図の全ソースの読み終わりを待つ（e2e-live/live.ts: settleMap）回数は、脚本が進める段の数だけ増える。
  timeout: 10 * 60_000,
  reporter: [["list"]],
  outputDir: "test-results/capture",
  use: {
    baseURL: process.env.CAPTURE_BASE_URL,
    actionTimeout: 15_000,
    // 手元のビルドは本番の backend を別オリジンとして呼ぶが、本番の backend の CORS は本番の frontend のオリジンしか許さない。
    launchOptions: localPort ? { args: ["--disable-web-security"] } : {},
  },
  projects: CHROMIUM_PROJECTS,
  webServer: localPort ? standaloneServer(localPort, process.env.CAPTURE_SERVER_DIR) : undefined,
});
