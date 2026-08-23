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
  // ローカル実行はworkers数を明示的に絞る（T252併用導入の実機検証で発覚）。既定のworkers数
  // （CPU論理コア数ベース）のまま3並列で実行すると、同一のwebServer（next start 1プロセス）
  // へ3つのヘッドレスChromiumが同時に地図（MapLibre GL・WASM）を読み込みに行き、ページ遷移・
  // beforeEachフックが軒並み30秒タイムアウトする事象を複数回実測した。workers=1へ絞ると
  // 同条件で安定して全green（該当コミットの実装メモ参照）。CIはGitHub Actions側のジョブ専有
  // リソースを前提に別途調整されているため対象外（process.env.CI判定）。
  workers: process.env.CI ? undefined : 1,
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
    // 本番Dockerfile（output: standalone、CMD ["node", "server.js"]）と同じエントリポイントで
    // 起動する。以前は`npm run start`（next start）を使っていたが、next.config.tsの
    // output: "standalone"とは組み合わせ不可という警告が出ており（T252併用導入の実機検証で
    // 発覚）、standalone構成固有の問題（静的アセット配置ずれ等）をE2Eが検知できない状態
    // だった。start:standaloneはDockerfileのCOPY相当（.next/static・public）を
    // scripts/prepare-standalone.mjsで再現してからnode .next/standalone/server.jsを
    // 起動する。next devは初回コンパイルの待ち時間が不安定でCIのタイムアウト調整が
    // しづらいため使わない。ローカル実行時は既存のdevサーバーを再利用できるよう
    // reuseExistingServerをCI以外でtrueにする。
    command: "npm run build && npm run start:standalone",
    url: "http://localhost:3000",
    timeout: 180_000,
    reuseExistingServer: !process.env.CI,
  },
});
