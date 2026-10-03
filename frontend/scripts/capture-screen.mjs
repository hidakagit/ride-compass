// モックした API で画面を開き、脚本で進めた状態を撮る（Pull Request の修正前後のキャプチャ。docs/conventions/flow.md「作る担当」の5）。
//
//   node scripts/capture-screen.mjs --script <脚本のファイル> [--ref <git の版>] [--size <幅>x<高さ>] [--theme light|dark]
//     [--out <出力のディレクトリ>] [--no-build]
//
// 応答は e2e/fixtures.ts: installApiMocks（backend も外部も要らない）。脚本は default export の関数（capture/screen.ts: ScreenScript）で、
// 受け取った open で開き、操作して shot で撮る。例は capture/examples/。脚本は作業ツリーの外に置いてもよい（.ts も読める）。
// 既定は作業ツリーの版をビルドして撮る。--ref は、その版の frontend を一時のディレクトリへ取り出し（作業ツリーは切り替えない）、
// 依存を入れてビルドして撮る（「前」。例: --ref origin/master）。取り出しとビルドは版の commit ごとに一時のディレクトリへ残し、
// 同じ commit なら使い回す。脚本と撮る段は、どちらの版でも作業ツリーのものを使う。
// 画像は <出力>/<版>/<番号>-<名前>.png（版は「作業ツリー」か --ref の値）。

import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { parseArgs } from "node:util";
import { LOCAL_PORT, fail, frontendRoot, parseSize, prepareBrowser, run, runCapture } from "./capture-common.mjs";

/** e2e/fixtures.ts: installApiMocks が待ち受ける向け先。ビルドの環境変数に別の向け先があっても、モックへ向ける。 */
const MOCKED_API = "http://localhost:8000";

const { values } = parseArgs({
  options: {
    script: { type: "string" },
    ref: { type: "string" },
    size: { type: "string", default: "390x812" },
    theme: { type: "string" },
    out: { type: "string", default: path.join(os.tmpdir(), "ridecompass-capture") },
    "no-build": { type: "boolean", default: false },
  },
});

if (!values.script) fail("--script <脚本のファイル> が要る（例: frontend/capture/examples/route-result.ts）");
const script = path.resolve(values.script);
if (!existsSync(script)) fail(`脚本が無い: ${script}`);
const viewport = parseSize(values.size);
if (values.theme && !["light", "dark"].includes(values.theme)) fail(`--theme は light か dark: ${values.theme}`);
const label = values.ref ?? "作業ツリー";
const out = path.join(path.resolve(values.out), label.replace(/[\\/:*?"<>|\s]+/g, "_"));
mkdirSync(out, { recursive: true });

/** --ref の版の frontend を取り出して依存を入れ、そのディレクトリを返す。 */
function checkoutRef(ref) {
  let commit;
  try {
    commit = execFileSync("git", ["rev-parse", "--verify", `${ref}^{commit}`], {
      cwd: frontendRoot,
      encoding: "utf-8",
    }).trim();
  } catch {
    fail(`--ref の版が無い: ${ref}（git fetch origin の後に打ち直す）`);
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
    const extract = spawnSync("tar", ["-x", "-f", "-", "-C", dir], { input: archive.stdout });
    if (extract.status !== 0) fail(`${ref} の frontend を展開できない: ${extract.stderr}`);
  }
  if (!existsSync(path.join(dir, "node_modules"))) {
    console.log(`[capture] ${ref}（${commit.slice(0, 12)}）の依存を入れる: ${dir}`);
    if (run("npm", ["ci", "--prefer-offline", "--no-audit", "--no-fund"], { cwd: dir }) !== 0)
      fail("依存を入れられない");
  }
  return { dir, built: existsSync(path.join(dir, ".next", "BUILD_ID")) };
}

prepareBrowser();

const target = values.ref ? checkoutRef(values.ref) : { dir: frontendRoot, built: false };
if (!values["no-build"] && !target.built) {
  console.log(`[capture] ${label} の版をビルドする`);
  const env = { NEXT_PUBLIC_API_URL: MOCKED_API, BACKEND_INTERNAL_URL: MOCKED_API };
  if (run("npm", ["run", "build"], { cwd: target.dir, env }) !== 0) fail("ビルドに失敗");
}

const status = runCapture("capture/screen.spec.ts", {
  CAPTURE_BASE_URL: `http://localhost:${LOCAL_PORT}`,
  CAPTURE_LOCAL_PORT: LOCAL_PORT,
  CAPTURE_SERVER_DIR: target.dir,
  CAPTURE_OPTIONS: JSON.stringify({ script, out, viewport, theme: values.theme ?? null }),
});
process.exit(status);
