// 担当のスロット（.claude/worktrees/ の coordinator.worktrees）を予約し、空きを出す。表は持たず、git の作業ツリーの鍵が状態を持つ:
// 振り出す側が鍵を掛けてから担当を起こし、担当は終わるときに枝を手放してから鍵を外す（git worktree unlock）。
// 鍵の掛かった作業ツリーは使用中で、理由（「tasks#<番号> <作る|確かめる> <掛けた時刻>」）の番号のキューの項目は動いている最中。
// 使い方: node tools/flow-gate/bin/slots.js [--json] [作業ツリーの名前...]（名前を省くと coordinator.worktrees）
//         node tools/flow-gate/bin/slots.js take <作業ツリーの名前> <issue の番号> <作る|確かめる>
import { execFileSync } from "node:child_process";
import { closeSync, existsSync, openSync, readFileSync, readdirSync, rmSync, writeSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import config from "../flow.config.json" with { type: "json" };

const USAGE = [
  "使い方: node tools/flow-gate/bin/slots.js [--json] [作業ツリーの名前...]",
  "        node tools/flow-gate/bin/slots.js take <作業ツリーの名前> <issue の番号> <作る|確かめる>",
].join("\n");
const KINDS = ["作る", "確かめる"];
const git = (dir, ...args) => execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" }).trim();
const common = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8" }).trim();
const root = join(common, "..", ".claude", "worktrees");
const REASON = new RegExp(`^tasks#(\\d+) (${KINDS.join("|")}) (\\S+)$`);

// 鍵は作業ツリーの管理の場所（<共通の .git>/worktrees/<名前>/）の locked で、中身が理由（git の文書「git-worktree」の DETAILS）。
// git worktree list --porcelain は ASCII 以外を含む理由やパスを引用符と8進で書くので、ファイルを直に読む。
const lockFile = (dir) => join(git(dir, "rev-parse", "--absolute-git-dir"), "locked");
const reasonOf = (file) => (existsSync(file) ? readFileSync(file, "utf8").trim() : null);
// 鍵の掛かった作業ツリーの、管理の場所の名前ごとの理由。
function locks() {
  const base = join(common, "worktrees");
  const out = new Map();
  for (const id of existsSync(base) ? readdirSync(base) : []) {
    const reason = reasonOf(join(base, id, "locked"));
    if (reason !== null) out.set(id, reason);
  }
  return out;
}

function take([slot, number, kind, ...rest]) {
  if (!slot || !/^\d+$/.test(number ?? "") || !KINDS.includes(kind) || rest.length) {
    console.error(USAGE);
    process.exit(2);
  }
  const dir = join(root, slot);
  if (!existsSync(dir)) {
    console.error(`スロット ${slot} の作業ツリーが無い`);
    process.exit(1);
  }
  // git worktree lock は鍵の有無を確かめてから別に書く（git のソースの lock_worktree）ので、その間に掛けた
  // 二人目も通りうる。鍵のファイルを排他で作ると、二人目は必ず失敗する。
  const file = lockFile(dir);
  let fd;
  try {
    fd = openSync(file, "wx");
  } catch (e) {
    if (e.code !== "EEXIST") throw e;
    console.error(`スロット ${slot} は使用中（${reasonOf(file) ?? "理由なし"}）`);
    process.exit(1);
  }
  writeSync(fd, `tasks#${number} ${kind} ${new Date().toISOString()}`);
  closeSync(fd);
  // 鍵が無いのに枝か変更を持つスロットは、鍵を掛けずに動いている担当か、片付けられていない残りなので使わない。
  const branch = git(dir, "branch", "--show-current");
  if (branch || git(dir, "status", "--porcelain") !== "") {
    rmSync(file);
    console.error(`スロット ${slot} は鍵が無いのに${branch ? `枝 ${branch} を持つ` : "未コミットの変更がある"}`);
    process.exit(1);
  }
  // 同じ番号を別のスロットで掛けた振り出しと同時なら、両方が相手を見つけて引く（どちらも担当を起こさない。次の振り出しが拾う）。
  const mine = basename(dirname(file));
  const other = [...locks()].find(([id, r]) => id !== mine && REASON.exec(r)?.[1] === number);
  if (other) {
    rmSync(file);
    console.error(`#${number} はスロット ${other[0]} が使っている（${other[1]}）`);
    process.exit(1);
  }
  console.log(`スロット ${slot} に鍵を掛けた（#${number} ${kind}）`);
}

function list(args) {
  const named = args.filter((a) => a !== "--json");
  const slots = named.length ? named : config.coordinator.worktrees;
  const rows = [];
  for (const slot of slots) {
    const dir = join(root, slot);
    if (!existsSync(dir)) {
      rows.push({ slot, state: "無い" });
      continue;
    }
    const branch = git(dir, "branch", "--show-current");
    const dirty = git(dir, "status", "--porcelain") !== "";
    const reason = reasonOf(lockFile(dir));
    if (reason === null) {
      rows.push({ slot, state: dirty ? "未コミットの変更あり" : branch ? "鍵の無い枝" : "空き", branch });
      continue;
    }
    const m = REASON.exec(reason);
    rows.push({
      slot,
      state: "使用中",
      kind: m?.[2] ?? "知らない鍵",
      number: m ? Number(m[1]) : null,
      reason,
      branch,
      minutes: m ? Math.round((Date.now() - Date.parse(m[3])) / 60000) : null,
    });
  }
  if (args.includes("--json")) console.log(JSON.stringify(rows, null, 2));
  else
    for (const r of rows)
      console.log(
        r.state === "使用中"
          ? r.number
            ? `${r.slot} 使用中 ${r.kind} #${r.number} ${r.minutes}分`
            : `${r.slot} 使用中 知らない鍵（${r.reason}）`
          : `${r.slot} ${r.state}${r.branch ? ` ${r.branch}` : ""}`,
      );
}

const args = process.argv.slice(2);
if (args[0] === "take") take(args.slice(1));
else if (args.some((a) => a.startsWith("--") && a !== "--json")) {
  console.error(USAGE);
  process.exit(2);
} else list(args);
