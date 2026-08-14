// Playwrightの動作確認用スモークスクリプト。
// `npm run dev`でNext.jsを起動した状態で `node scripts/smoke-check.mjs` を実行すると、
// headless Chromiumでトップページを開きスクリーンショットを撮る。
// エージェントがUI検証のたびにscratchpadへPlaywrightを一時インストールし直す必要が
// ないよう、プロジェクトのdevDependencyとして導入した動作確認用。
import { chromium } from "playwright";

const url = process.argv[2] ?? "http://localhost:3000";
const outPath = process.argv[3] ?? "scripts/.smoke-check-screenshot.png";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
await page.goto(url, { waitUntil: "load" });
await page.screenshot({ path: outPath });
await browser.close();

console.log(`OK: screenshot saved to ${outPath}`);
