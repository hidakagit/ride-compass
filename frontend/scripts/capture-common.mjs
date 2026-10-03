// 画面を撮る入口（scripts/capture-map.mjs・scripts/capture-screen.mjs）が共有する段取り。

import { execFileSync, spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const frontendRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
/** frontend/e2e（3100）・e2e-live（3200）・devサーバー（3000）と取り合わないポート。 */
export const LOCAL_PORT = "3300";
const playwright = path.join(frontendRoot, "node_modules", "@playwright", "test", "cli.js");

export function fail(message) {
  console.error(`[capture] ${message}`);
  process.exit(1);
}

export function run(command, args, { cwd = frontendRoot, env = {} } = {}) {
  const result = spawnSync(command, args, {
    cwd,
    stdio: "inherit",
    env: { ...process.env, ...env },
    shell: process.platform === "win32",
  });
  return result.status ?? 1;
}

/** `<幅>x<高さ>` を読む。 */
export function parseSize(size) {
  const [width, height] = size.split("x").map(Number);
  if (!(width > 0 && height > 0)) fail(`--size は <幅>x<高さ>（例: 390x812）: ${size}`);
  return { width, height };
}

/** Playwright の Chromium と、Linux なら日本語のフォント（無いと文字が豆腐になる）を入れる。 */
export function prepareBrowser() {
  if (run(process.execPath, [playwright, "install", "chromium"]) !== 0) fail("Chromium を入れられない");
  if (process.platform !== "linux") return;
  const japanese = () => {
    try {
      return execFileSync("fc-list", [":lang=ja"], { encoding: "utf-8" }).trim().length > 0;
    } catch {
      return false;
    }
  };
  if (japanese()) return;
  console.log("[capture] 日本語のフォントが無いので fonts-noto-cjk を入れる");
  run("sudo", ["-n", "apt-get", "install", "-y", "-q", "fonts-noto-cjk"]);
  if (!japanese()) fail("日本語のフォントを入れられない（fonts-noto-cjk 等を入れてから打ち直す）");
}

/** playwright.capture.config.ts で `spec` の段を流す。 */
export function runCapture(spec, env) {
  return run(process.execPath, [playwright, "test", "-c", "playwright.capture.config.ts", spec], { env });
}
