// 道具（bin/*.js）の共通部分: master の版で打つこと・設定・トークン・引数。
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import config from "../flow.config.json" with { type: "json" };
import { GitHub } from "../src/github.js";

export { config };

// 道具は master の版で書く。作業ブランチの道具は master で道具が変わる前の写しのことがあり、古い形のまま書き込む。
// この作業ツリーの tools/flow-gate が origin/master と違えば、master の版を一時の場所へ取り出し、同じ引数でそちらを打って、
// その終わりの値で終える。取り出した側は、元のリポジトリを FLOW_GATE_REPO で受け取る。試し（--dry-run）は書かないので、
// 作業ツリーの版で打つ（道具を変える作業ブランチで、変えた道具を試す）。
const ref = `origin/${config.code.base}`;
export const repo = process.env.FLOW_GATE_REPO
  ?? execFileSync("git", ["-C", fileURLToPath(new URL(".", import.meta.url)), "rev-parse", "--show-toplevel"], { encoding: "utf8" }).trim();
export const git = (...a) => execFileSync("git", ["-C", repo, ...a], { encoding: "utf8" });
if (!process.env.FLOW_GATE_REPO && !process.argv.includes("--dry-run")) {
  try {
    git("fetch", "-q", "origin", config.code.base);
  } catch {
    console.error(`origin の ${config.code.base} を取れなかったので、手元にある ${ref} を master の版とする`);
  }
  if (git("diff", "--name-only", ref, "--", "tools/flow-gate").trim()) {
    const copy = join(tmpdir(), `flow-gate-${git("rev-parse", `${ref}:tools/flow-gate`).trim()}`);
    if (!existsSync(copy)) {
      const part = `${copy}.${process.pid}`;
      for (const file of git("ls-tree", "-r", "--name-only", ref, "--", "tools/flow-gate").split("\n").filter(Boolean)) {
        mkdirSync(dirname(join(part, file)), { recursive: true });
        writeFileSync(join(part, file), execFileSync("git", ["-C", repo, "show", `${ref}:${file}`]));
      }
      try {
        renameSync(part, copy);
      } catch {
        rmSync(part, { recursive: true, force: true }); // 同時に打った別の道具が先に取り出した
      }
    }
    console.error(`この作業ツリーの道具は ${ref} と違うので、${ref} の版で打つ`);
    const run = spawnSync(process.execPath, [join(copy, relative(repo, process.argv[1])), ...process.argv.slice(2)],
      { stdio: "inherit", env: { ...process.env, FLOW_GATE_REPO: repo } });
    process.exit(run.status ?? 1);
  }
}

// トークンは環境変数から読む（Actions では秘密の値から渡る）。Windows のユーザー環境変数は、それより前に起動したプロセスに
// 入らないので、無ければ登録簿から読む。
function userEnv(name) {
  if (process.env[name]) return process.env[name];
  if (process.platform !== "win32") throw new Error(`環境変数 ${name} が無い`);
  return new RegExp(`${name}\\s+REG_SZ\\s+(\\S+)`).exec(execFileSync("reg", ["query", "HKCU\\Environment", "/v", name], { encoding: "utf8" }))[1];
}
export const bot = () => new GitHub(userEnv("FLOW_BOT_TOKEN")); // 置き場へ書くのは hidakagit-bot だけ
export const code = () => new GitHub(userEnv("GH_TOKEN")); // コードのリポジトリ（hidakagit のもの）を読み、担当を起こす

// 引数を読む。usage は使い方の1行で、試しを持つ道具は `[--dry-run]` を書く。ok は引数（--dry-run を除いたもの）が正しいか。
// 正しくなければ使い方を出して 2 で終える。試しを持たない道具に --dry-run が付いていれば、本当に書かないよう何もせずに 1 で終える
// （--dry-run が付くと上で master の版へ打ち直さないので、ここで断るのは作業ツリーの版）。
export function args(usage, ok) {
  const all = process.argv.slice(2);
  const dry = all.includes("--dry-run");
  if (dry && !usage.includes("[--dry-run]")) {
    console.error(`この道具は試し（--dry-run）を持たないので、何もせずに終える。使い方: ${usage}`);
    process.exit(1);
  }
  const rest = all.filter((a) => a !== "--dry-run");
  if (!ok(rest)) {
    console.error(`使い方: ${usage}`);
    process.exit(2);
  }
  return { dry, rest };
}
export const isNumber = (s) => /^\d+$/.test(s ?? "");
