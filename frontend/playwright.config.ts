import { defineConfig, devices } from "@playwright/test";

// 何をE2Eの対象にするかは docs/conventions/testing.md パターン4。
// 実バックエンド・実外部APIには依存しない（e2e/fixtures.ts）。

/** E2E専用のポート。devサーバー（3000）や他の作業ツリーのサーバーと取り合わない。 */
const E2E_PORT = 3100;
const E2E_ORIGIN = `http://localhost:${E2E_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // 1つのサーバーへ複数のChromiumが同時に地図（MapLibre・WASM）を読みに行くと、開発機では
  // ページ遷移とフックが30秒の枠を超える。CIのランナーはジョブ専有なので既定のまま。
  workers: process.env.CI ? undefined : 1,
  // CIは失敗時にplaywright-reportをartifactとして上げる（ci.yml）。
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "html",
  use: {
    baseURL: E2E_ORIGIN,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    // 起動だけを行う。ビルドは`npm run test:e2e`が先に済ませる——ビルドをここへ入れると、
    // 開発機ではビルドだけで起動待ちの枠を使い切る。本番Dockerfileと同じ
    // `node .next/standalone/server.js`を、同じ静的ファイルの配置（prepare-standalone.mjs）で起動する。
    command: "npm run start:standalone",
    url: E2E_ORIGIN,
    // standaloneのserver.jsは待ち受けるアドレスを環境変数HOSTNAMEから取る。Git Bashはこれへ機械名を
    // exportするので、固定しないと機械名の解決先（IPv6のアドレス等）でしか待ち受けず、localhostへ届かない。
    env: { PORT: String(E2E_PORT), HOSTNAME: "localhost" },
    timeout: 60_000,
    // 既に動いているサーバー（devサーバー・古いビルド）を使うと、いまのビルドを試さない。
    reuseExistingServer: false,
  },
});
