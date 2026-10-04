// 画面を、選んだ版と応答で開き、脚本で進めた状態を撮る（Pull Request の修正前後のキャプチャ。docs/conventions/flow.md「作る担当」の5）。
//
//   node scripts/capture.mjs [--script <脚本のファイル>] [--app production|worktree|<git の版>] [--api mock|<backend のオリジン>]
//     [--size <幅>x<高さ>] [--theme light|dark] [--out <出力のディレクトリ>] [--no-build]
//
// --app は開く版: production は本番の frontend をそのまま開く（本番の backend を使うので --api を受けない）。worktree（既定）は
// 作業ツリーの版を、<git の版>（例: origin/master）はその版を一時のディレクトリへ取り出して（作業ツリーは切り替えない）、ビルドして
// 手元で起動する。取り出しとビルドは版の commit と --api ごとに使い回す。
// --api は応答: mock（既定）は e2e/fixtures.ts: installApiMocks（backend も外部も要らない）。<backend のオリジン> は本物の backend で、
// 地図の塗り（道路タイル）はこちらでしか出ない（本番の宛先は docs/architecture/tech-stack.md「本番の宛先」）。
// 脚本は default export の関数（capture/context.ts: CaptureScript）で、受け取った口（open・chooseLens・openLegend・patch・shot 等）
// だけを使い、何も読み込まない。作業ツリーの外に置いてよい（.ts も読める）。省略すると開いて1枚撮る。例は capture/examples/。
// 撮る前に、宛先（本番の frontend・本物の backend）が応答するまで待ち、Playwright の Chromium と、Linux なら起こすのに要る依存と
// 日本語のフォント（無いと文字が豆腐になる）を入れる。画像は <出力>/<版>/<番号>-<名前>.png。

import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const frontendRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const playwright = path.join(frontendRoot, "node_modules", "@playwright", "test", "cli.js");
const PRODUCTION_FRONTEND = "https://ride-compass-frontend.onrender.com";
/** e2e/fixtures.ts: installApiMocks が待ち受ける向け先。ビルドの環境変数に別の向け先があっても、モックへ向ける。 */
const MOCKED_API = "http://localhost:8000";
/** frontend/e2e（3100）・e2e-live（3200）・devサーバー（3000）と取り合わないポート。 */
const LOCAL_PORT = "3300";
/** Render の無料のインスタンスは休止から起きるのに約1分かかる（https://render.com/docs/free）。その3倍まで待つ。 */
const WAKE_LIMIT_MS = 3 * 60_000;

function fail(message) {
  console.error(`[capture] ${message}`);
  process.exit(1);
}

/**
 * Windows の npm は .cmd で、.cmd はシェル越しでしか起こせない。シェル越しの引数は引用されず、空白を含むパス（例: process.execPath）は
 * 切れるので、絶対パスで渡す実行ファイルはシェルを通さない。
 */
function run(command, args, { cwd = frontendRoot, env = {} } = {}) {
  const result = spawnSync(command, args, {
    cwd,
    stdio: "inherit",
    env: { ...process.env, ...env },
    shell: process.platform === "win32" && !path.isAbsolute(command),
  });
  return result.status ?? 1;
}

const { values } = parseArgs({
  options: {
    script: { type: "string" },
    app: { type: "string", default: "worktree" },
    api: { type: "string" },
    size: { type: "string", default: "390x812" },
    theme: { type: "string" },
    out: { type: "string", default: path.join(os.tmpdir(), "ridecompass-capture") },
    "no-build": { type: "boolean", default: false },
  },
});

const production = values.app === "production";
if (production && values.api) fail("--app production は本番の backend を使う（--api を外す）");
const api = values.api?.replace(/\/+$/, "") ?? "mock";
const mocked = !production && api === "mock";
const script = values.script ? path.resolve(values.script) : null;
if (script && !existsSync(script)) fail(`脚本が無い: ${script}`);
const [width, height] = values.size.split("x").map(Number);
if (!(width > 0 && height > 0)) fail(`--size は <幅>x<高さ>（例: 390x812）: ${values.size}`);
if (values.theme && !["light", "dark"].includes(values.theme)) fail(`--theme は light か dark: ${values.theme}`);
const label = { production: "本番", worktree: "作業ツリー" }[values.app] ?? values.app;
const out = path.join(path.resolve(values.out), label.replace(/[\\/:*?"<>|\s]+/g, "_"));
mkdirSync(out, { recursive: true });

/** Chromium を入れて起こせるかを試し、Linux なら起こすのに要る依存と日本語のフォントを入れる。 */
function prepareBrowser() {
  if (run(process.execPath, [playwright, "install", "chromium"]) !== 0) fail("Chromium を入れられない");
  if (process.platform !== "linux") return;
  const launches = () =>
    spawnSync(
      process.execPath,
      [
        "-e",
        "require('@playwright/test').chromium.launch().then((b) => b.close()).then(() => process.exit(0), () => process.exit(1))",
      ],
      { cwd: frontendRoot },
    ).status === 0;
  if (!launches()) {
    console.log("[capture] Chromium を起こせないので、起こすのに要る依存を入れる");
    run("sudo", ["-n", process.execPath, playwright, "install-deps", "chromium"]);
    if (!launches())
      fail(
        `Chromium を起こせない（sudo ${process.execPath} ${playwright} install-deps chromium を打ってから打ち直す）`,
      );
  }
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

/** 宛先が 200 の JSON を返すまで待つ。休止中の宛先は、起きるまで応答を待たせるか、起動待ちの画面（HTML）を返す。 */
async function waitReady(name, url) {
  const deadline = Date.now() + WAKE_LIMIT_MS;
  const started = Date.now();
  let last = "応答なし";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(Math.max(1, deadline - Date.now())) });
      if (response.ok && (response.headers.get("content-type") ?? "").includes("json")) {
        console.log(`[capture] ${name} が応答した（${((Date.now() - started) / 1000).toFixed(1)}秒）`);
        return;
      }
      last = `${response.status} ${response.headers.get("content-type") ?? ""}`;
    } catch (error) {
      last = String(error.cause ?? error);
    }
    await new Promise((resolve) => setTimeout(resolve, 5_000));
  }
  fail(`${name} が ${WAKE_LIMIT_MS / 60_000} 分たっても起きない（${url} の最後の応答: ${last}）`);
}

/** <git の版> の frontend を取り出して依存を入れ、そのディレクトリを返す。 */
function checkoutRef(ref) {
  let commit;
  try {
    commit = execFileSync("git", ["rev-parse", "--verify", `${ref}^{commit}`], {
      cwd: frontendRoot,
      encoding: "utf-8",
    }).trim();
  } catch {
    fail(`--app の版が無い: ${ref}（git fetch origin の後に打ち直す）`);
  }
  const dir = path.join(os.tmpdir(), `ridecompass-capture-${commit.slice(0, 12)}`, "frontend");
  if (!existsSync(path.join(dir, "package.json"))) {
    mkdirSync(dir, { recursive: true });
    // git archive はサブディレクトリから打つとその下へ絞るので、リポジトリの根から打つ。
    const archive = spawnSync("git", ["archive", `${commit}:frontend`], {
      cwd: path.dirname(frontendRoot),
      maxBuffer: 1 << 30,
    });
    if (archive.status !== 0) fail(`${ref} の frontend を取り出せない: ${archive.stderr}`);
    // 展開の先は引数でなく作業ディレクトリで渡す: Git Bash の GNU tar は `C:` を含むパスを別のマシンの名前と読んで開けない。
    const extract = spawnSync("tar", ["-x", "-f", "-"], { cwd: dir, input: archive.stdout });
    if (extract.status !== 0) fail(`${ref} の frontend を展開できない: ${extract.stderr}`);
  }
  if (!existsSync(path.join(dir, "node_modules"))) {
    console.log(`[capture] ${ref}（${commit.slice(0, 12)}）の依存を入れる: ${dir}`);
    if (run("npm", ["ci", "--prefer-offline", "--no-audit", "--no-fund"], { cwd: dir }) !== 0)
      fail("依存を入れられない");
  }
  return dir;
}

/** ビルドに埋め込んだ向け先。同じ版でも --api が違えばビルドし直す。 */
function builtFor(dir) {
  const marker = path.join(dir, ".next", "capture-api");
  return existsSync(path.join(dir, ".next", "BUILD_ID")) && existsSync(marker) ? readFileSync(marker, "utf-8") : null;
}

prepareBrowser();

let serverDir = null;
if (!production) {
  serverDir = values.app === "worktree" ? frontendRoot : checkoutRef(values.app);
  const target = mocked ? MOCKED_API : api;
  const reuse = values["no-build"] || (serverDir !== frontendRoot && builtFor(serverDir) === target);
  if (!reuse) {
    console.log(`[capture] ${label} の版をビルドする（API: ${mocked ? "モック" : target}）`);
    if (
      run("npm", ["run", "build"], {
        cwd: serverDir,
        env: { NEXT_PUBLIC_API_URL: target, BACKEND_INTERNAL_URL: target },
      }) !== 0
    ) {
      fail("ビルドに失敗");
    }
    writeFileSync(path.join(serverDir, ".next", "capture-api"), target);
  }
}

if (production) await waitReady("本番の frontend", `${PRODUCTION_FRONTEND}/api/version`);
if (!mocked && !production) await waitReady("backend", `${api}/health`);

const status = run(process.execPath, [playwright, "test", "-c", "playwright.capture.config.ts"], {
  env: {
    CAPTURE_BASE_URL: production ? PRODUCTION_FRONTEND : `http://localhost:${LOCAL_PORT}`,
    ...(serverDir ? { CAPTURE_LOCAL_PORT: LOCAL_PORT, CAPTURE_SERVER_DIR: serverDir } : {}),
    CAPTURE_OPTIONS: JSON.stringify({
      script,
      out,
      mocked,
      viewport: { width, height },
      theme: values.theme ?? null,
    }),
  },
});
process.exit(status);
