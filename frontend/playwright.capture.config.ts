import { defineConfig, devices } from "@playwright/test";

// 画面を撮る段（frontend/capture/）。テストではなく、CI にも載せない。入口と引数は scripts/capture-map.mjs・scripts/capture-screen.mjs が
// 持ち、宛先を環境変数で渡す: CAPTURE_BASE_URL（撮る画面のオリジン）と、手元のビルドを撮るときの CAPTURE_LOCAL_PORT・
// CAPTURE_SERVER_DIR（ビルドのある frontend。既定はこの作業ツリー）。

const localPort = process.env.CAPTURE_LOCAL_PORT;

export default defineConfig({
  testDir: "./capture",
  workers: 1,
  retries: 0,
  // 地図の全ソースの読み終わりを待つ（e2e-live/live.ts: settleMap）回数は、撮るレンズの数だけ増える。
  timeout: 10 * 60_000,
  reporter: [["list"]],
  outputDir: "test-results/capture",
  use: {
    baseURL: process.env.CAPTURE_BASE_URL,
    actionTimeout: 15_000,
    // 手元のビルドは本番の backend を別オリジンとして呼ぶが、本番の backend の CORS は本番の frontend のオリジンしか許さない。
    launchOptions: localPort ? { args: ["--disable-web-security"] } : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: localPort
    ? {
        command: "npm run start:standalone",
        cwd: process.env.CAPTURE_SERVER_DIR,
        url: `http://localhost:${localPort}`,
        // Git Bash は HOSTNAME へ機械名を入れて export する。standalone のサーバーは HOSTNAME で待ち受けるので、localhost へ固定する。
        env: { PORT: localPort, HOSTNAME: "localhost" },
        timeout: 60_000,
        reuseExistingServer: false,
      }
    : undefined,
});
