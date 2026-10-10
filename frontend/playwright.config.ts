import { defineConfig, devices, type PlaywrightTestConfig } from "@playwright/test";

// 何をE2Eの対象にするかは .claude/rules/testing-e2e.md パターン4。
// 実バックエンド・実外部APIには依存しない（e2e/fixtures.ts）。

/** E2E専用のポート。devサーバー（3000）や他の作業ツリーのサーバーと取り合わない。 */
const E2E_PORT = 3100;
const E2E_ORIGIN = `http://localhost:${E2E_PORT}`;

/** ブラウザはChromiumだけにする（.claude/rules/testing-e2e.md パターン4）。 */
export const CHROMIUM_PROJECTS = [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }];

/**
 * 本番Dockerfileと同じ`node .next/standalone/server.js`を、同じ静的ファイルの配置（prepare-standalone.mjs）で起動する。
 * 起動だけを行い、ビルドは呼び手が先に済ませる。`cwd`はビルドのあるfrontend（既定はこの設定のある所）。
 */
export function standaloneServer(port: number | string, cwd?: string): PlaywrightTestConfig["webServer"] {
  return {
    command: "npm run start:standalone",
    cwd,
    url: `http://localhost:${port}`,
    // standaloneのserver.jsは待ち受けるアドレスを環境変数HOSTNAMEから取る。Git Bashはこれへ機械名を
    // exportするので、固定しないと機械名の解決先（IPv6のアドレス等）でしか待ち受けず、localhostへ届かない。
    env: { PORT: String(port), HOSTNAME: "localhost" },
    timeout: 60_000,
    // 既に動いているサーバー（devサーバー・古いビルド）を使うと、いまのビルドを試さない。
    reuseExistingServer: false,
  };
}

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // 再試行しない（.claude/rules/testing-scaffold.md「テストの足場で、本来のNGを覆わない」）。
  retries: 0,
  // 1つのサーバーへ複数のChromiumが同時に地図（MapLibre・WASM）を読みに行くと、開発機では
  // ページ遷移とフックが30秒の枠を超える。CIのランナーはジョブ専有なので既定のまま。
  workers: process.env.CI ? undefined : 1,
  // CIは失敗時にplaywright-reportをartifactとして上げる（ci.yml）。
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "html",
  use: {
    baseURL: E2E_ORIGIN,
    trace: "retain-on-failure",
  },
  projects: CHROMIUM_PROJECTS,
  // ビルドは`npm run test:e2e`が先に済ませる——ビルドをここへ入れると、開発機ではビルドだけで起動待ちの枠を使い切る。
  webServer: standaloneServer(E2E_PORT),
});
