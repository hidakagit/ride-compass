import { defineConfig, devices } from "@playwright/test";

// CIのE2Eスモークテスト用設定（改善計画「別の切り口」対応）。
// 対象はクリティカルパス（ルート生成→表示、レイヤー切替）のみで、実バックエンド・
// 実外部APIには依存しない（e2e/fixtures.ts参照）。ブラウザはChromium1種のみで
// 十分（クロスブラウザ差異の検証が目的ではなく、フロントのリグレッション検知が目的）。
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // CIは失敗時のみplaywright-reportをartifactとしてアップロードする（ci.yml参照）ため、
  // 標準出力向けのlineに加えhtmlレポートも常に生成しておく。
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "html",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    // next start（プロダクションビルド）を使う。next devは初回コンパイルの待ち時間が
    // 不安定でCIのタイムアウト調整がしづらいため。ローカル実行時は既存のdevサーバーを
    // 再利用できるようreuseExistingServerをCI以外でtrueにする。
    command: "npm run build && npm run start",
    url: "http://localhost:3000",
    timeout: 180_000,
    reuseExistingServer: !process.env.CI,
  },
});
