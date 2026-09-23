import { defineConfig, devices } from "@playwright/test";

// 実backend・開発DBへ向けて回すe2e（frontend/e2e-live/）。CIには載せない。何を守るか・前提・走らせ方・誰がいつ回すかは
// docs/conventions/testing.md パターン4「走らせ方」。backendはここから起動しない——DBの向け先・.envは人ごとに違い、
// 設定ファイルが向け先を決めることになるため。前提はglobalSetupが最初に確かめる。

/** `frontend/e2e/`（3100）・devサーバー（3000）と取り合わないポート。backendの基礎地図のURLとCORSもこのオリジンに合わせる。 */
const LIVE_PORT = 3200;
export const LIVE_ORIGIN = `http://localhost:${LIVE_PORT}`;

export default defineConfig({
  testDir: "./e2e-live",
  globalSetup: "./e2e-live/global-setup.ts",
  // 開発DBと手元のbackendは1つなので、ルート生成の同時実行・レート制限（429）を避けて1本ずつ。
  workers: 1,
  fullyParallel: false,
  retries: 0,
  // 1シナリオ＝1本の幹で、幹の段取り（実データでの地図の読み込み・ルート生成）が重い。
  timeout: 8 * 60_000,
  reporter: [["list"]],
  use: {
    baseURL: LIVE_ORIGIN,
    // 見つからない部品を押そうとして、シナリオの時間切れまで待ち続けない（枝の失敗として出して次の枝へ進む）。
    actionTimeout: 15_000,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run start:standalone",
    url: LIVE_ORIGIN,
    // Git BashはHOSTNAMEへ機械名を入れてexportする。standaloneのサーバーはHOSTNAMEで待ち受けるので、localhostへ固定する。
    env: { PORT: String(LIVE_PORT), HOSTNAME: "localhost" },
    timeout: 60_000,
    reuseExistingServer: false,
  },
});
