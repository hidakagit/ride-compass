import { defineConfig } from "@playwright/test";

import base from "./playwright.config";

// アプリのサーバーを要らない e2e を、ビルドとサーバーの起動無しで手元で回す（走らせ方は docs/conventions/testing-operations.md
// 「E2E・画面の撮影の走らせ方」）。`webServer` は project ごとには分けられないので、設定を分ける。CI は `playwright.config.ts` で
// ここの spec も回す。

export default defineConfig({
  ...base,
  // 架空のオリジンへ `page.route` で応答を返し、アプリを開かない spec だけ。
  testMatch: ["recording-map.spec.ts"],
  webServer: undefined,
});
