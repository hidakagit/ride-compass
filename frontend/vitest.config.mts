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
    // vitest既定のtestTimeout(5000ms)は、依存を入れた直後のコールドスタート（Viteの変換・DOM環境の
    // 準備が初回だけ長い）と競合し、実装が正しくてもテストがタイムアウトで落ちる。余裕を持たせた値にする。
    testTimeout: 15000,
    // 下記environmentの構築（happy-dom）はテストファイルごとに走り、テスト本体より大きな
    // 時間を占める。vmThreadsはワーカースレッド内のVMコンテキストを使い回すため、この構築が
    // ファイル数ぶん繰り返されない。モジュールレジストリはファイルごとに分かれたままなので、
    // vi.mockやモジュールスコープの状態が他のファイルへ漏れることはない（速度目的で
    // isolate: falseへ倒すと漏れる。後述コメント参照）。
    // forksプール（vitestの既定）はテストファイルごとにOSプロセスを起こすため、プロセス
    // 起動が重いWindowsでは支配的なオーバーヘッドになる（[vitest-pool]: Timeout
    // terminating forks workerが頻発する）。
    pool: "vmThreads",
    // 既定のDOM環境はhappy-dom（jsdomより環境の準備もテスト本体も速い）。happy-domで挙動の違うAPIに
    // 当たったら、そのファイルに`// @vitest-environment jsdom`のdocblockを付けてjsdomで動かす。
    // `isolate: false`（ファイル間でモジュール状態・DOM環境を使い回す）は、実行のたびに違うテストが
    // 落ちるため使わない（docs/conventions/testing.md「基本原則」の3: 速度の最適化は確かめる内容を変えない範囲で行う）。
    environment: "happy-dom",
    // backendは画面と別のオリジンにあり、happy-domの`fetch`はCORSの事前の要求（OPTIONS）を出して応答の見出しを照らす。
    // CORSを許すのはbackendの設定で、画面のテストが見るものではないため外す（外さないと、網の層の差し替え
    // `src/testing/backendServer.ts`が、口の要求の前に応答の無いOPTIONSを受けて落とす）。
    environmentOptions: { happyDOM: { settings: { fetch: { disableSameOriginPolicy: true } } } },
    // DOM環境の準備はテストファイルごとに走るので、DOMを使わないファイル（render・renderHook・window等を
    // 使わない純ロジック）はファイルの先頭の`// @vitest-environment node`docblockでnode環境に倒す。
    // 設定での一括の振り分け（`environmentMatchGlobs`）はVitest 4に無く、代わりの`test.projects`は
    // 対象のパターンに入らないテストファイルを黙って外しうるため使わない。docblockの無いファイルは既定の
    // happy-domで動くので、DOMを後から使い始めても黙って壊れない（docs/conventions/testing.md「パターン3」）。
    setupFiles: ["./vitest.setup.ts"],
    css: true,
    // frontend/e2e/・frontend/e2e-live/・frontend/capture/はPlaywright（別ランナー）専用のため、
    // vitestのデフォルトテスト探索（*.spec.ts）から除外する。
    // .claude/worktrees/配下は並行セッションが作るgit worktree（他ブランチのfrontend/を丸ごと含む）で、
    // 拾うと別の版のテストまで流れる。configDefaults.excludeはnode_modules配下しか外さないため明示的に外す。
    exclude: [...configDefaults.exclude, "e2e/**", "e2e-live/**", "capture/**", "**/.claude/worktrees/**"],
  },
});
