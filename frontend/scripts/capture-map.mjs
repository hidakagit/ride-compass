// 地図の画面を、指定の位置・幅・レンズで撮る（Pull Request の修正前後のキャプチャ。docs/conventions/flow.md「作る担当」の5）。
//
//   node scripts/capture-map.mjs [--url <frontend のオリジン> | --local --api <backend のオリジン>] [--lens <レンズの名前>]...
//     [--point <緯度,経度>] [--size <幅>x<高さ>] [--zoom <倍率>] [--theme light|dark] [--replace <URL の glob>=<ファイル>]...
//     [--out <出力のディレクトリ>] [--no-build]
//
// 既定は本番の画面（--url の既定）。--local は作業ツリーの版をビルドして手元で起動し、API とタイルを --api の backend へ向けて撮る
// （本番に出る前の版。地図の塗りに要る道路タイルは backend が持つので、本番の backend へ向ければ開発 DB は要らない）。
// --replace は、URL が glob に当たる応答の本文を差し替える。.json はファイルの中身で、.mjs は default export の関数（本物の JSON を
// 受け取って返す）で替える。撮る前に Playwright の Chromium と、Linux なら日本語のフォント（無いと文字が豆腐になる）を入れる。

import { mkdirSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { parseArgs } from "node:util";
import { LOCAL_PORT, fail, parseSize, prepareBrowser, run, runCapture } from "./capture-common.mjs";

const PRODUCTION_FRONTEND = "https://ride-compass-frontend.onrender.com";

const { values } = parseArgs({
  options: {
    url: { type: "string", default: PRODUCTION_FRONTEND },
    local: { type: "boolean", default: false },
    api: { type: "string" },
    lens: { type: "string", multiple: true, default: [] },
    point: { type: "string" },
    size: { type: "string", default: "390x812" },
    zoom: { type: "string" },
    theme: { type: "string" },
    replace: { type: "string", multiple: true, default: [] },
    out: { type: "string", default: path.join(os.tmpdir(), "ridecompass-capture") },
    "no-build": { type: "boolean", default: false },
  },
});

const { width, height } = parseSize(values.size);
if (values.theme && !["light", "dark"].includes(values.theme)) fail(`--theme は light か dark: ${values.theme}`);
if (values.local && !values.api) {
  fail("--local には --api <backend のオリジン> が要る（本番の宛先は docs/architecture/tech-stack.md「本番の宛先」）");
}
const replace = values.replace.map((entry) => {
  const at = entry.lastIndexOf("=");
  if (at <= 0) fail(`--replace は <URL の glob>=<ファイル>: ${entry}`);
  return { glob: entry.slice(0, at), file: path.resolve(entry.slice(at + 1)) };
});
const out = path.resolve(values.out);
mkdirSync(out, { recursive: true });

prepareBrowser();

if (values.local && !values["no-build"]) {
  const api = values.api.replace(/\/+$/, "");
  if (run("npm", ["run", "build"], { env: { NEXT_PUBLIC_API_URL: api, BACKEND_INTERNAL_URL: api } }) !== 0) {
    fail("ビルドに失敗");
  }
}

const status = runCapture("capture/map.spec.ts", {
  CAPTURE_BASE_URL: values.local ? `http://localhost:${LOCAL_PORT}` : values.url,
  ...(values.local ? { CAPTURE_LOCAL_PORT: LOCAL_PORT } : {}),
  ...(values.point ? { E2E_LIVE_POINT: values.point } : {}),
  CAPTURE_OPTIONS: JSON.stringify({
    lenses: values.lens,
    out,
    viewport: { width, height },
    zoom: values.zoom === undefined ? null : Number(values.zoom),
    theme: values.theme ?? null,
    replace,
  }),
});
process.exit(status);
