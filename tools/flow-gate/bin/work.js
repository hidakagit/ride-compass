// 担当の起動役。dispatch.js が鍵を掛けたスロットで切り離して起こす。担当（claude -p）を起こし、担当のプロセスが終わった
// 瞬間に後始末をする: 作る担当が Pull Request も問いも出さずに終わった（issue が振り出した状態のまま）なら落ちたとみなして
// 保留にする → スロットに未コミットの変更が無ければ枝を手放して鍵を外す（あれば鍵ごと残す）→ 状況の更新を書く → 次の振り出し
// （dispatch.js）を起こす。担当は作業と報告だけをし、鍵・スロット・振り出しには触れない。
// 起動役ごと消えた（PC の再起動等）スロットは、dispatch.js が --finish で同じ後始末をする。
// 使い方: node tools/flow-gate/bin/work.js <スロット> <issue の番号> <作る|確かめる>
//         node tools/flow-gate/bin/work.js --finish <スロット> [--no-dispatch]（--no-dispatch は後始末のあと司令塔を起こさない。司令塔から呼ぶとき）
import { execFileSync, spawn } from "node:child_process";
import { mkdirSync, openSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import config from "../flow.config.json" with { type: "json" };
import { GitHub, readTask } from "../src/github.js";
import { botToken } from "./token.js";

const here = dirname(fileURLToPath(import.meta.url));
const git = (dir, ...rest) => execFileSync("git", ["-C", dir, ...rest], { encoding: "utf8" }).trim();
const root = join(git(here, "rev-parse", "--path-format=absolute", "--git-common-dir"), "..");
const slotDir = (slot) => join(root, ".claude", "worktrees", slot);
const tool = (script, ...rest) => {
  try {
    return execFileSync(process.execPath, [join(here, script), ...rest], { encoding: "utf8" }).trim();
  } catch (e) {
    return `${script} が失敗: ${String(e.stderr || e.message).trim()}`;
  }
};
const log = (line) => console.log(`${new Date().toISOString()} ${line}`);

const args = process.argv.slice(2);
if (args[0] === "--finish" && (args.length === 2 || (args.length === 3 && args[2] === "--no-dispatch"))) {
  const s = JSON.parse(tool("slots.js", "--json", args[1]))[0];
  if (s?.state !== "使用中" || !s.number) process.exit(0);
  await finish(args[1], s.number, s.kind, "起動役が見つからない（PC の再起動や、手で止められた）", args[2] !== "--no-dispatch");
} else if (args.length === 3 && /^\d+$/.test(args[1]) && ["作る", "確かめる"].includes(args[2])) {
  const [slot, number, kind] = args;
  tool("slots.js", "pid", slot, String(process.pid));
  log(`#${number} の${kind}担当を起こす（スロット ${slot}）`);
  log(tool("status.js"));
  const code = await run(slot, Number(number), kind);
  await finish(slot, Number(number), kind, `担当のプロセスが終了コード ${code} で終わった`);
} else {
  console.error("使い方: node tools/flow-gate/bin/work.js <スロット> <issue の番号> <作る|確かめる> | --finish <スロット>");
  process.exit(2);
}

// 担当を起こし、終わるまで待つ。出力はスロットごとの記録に残す（.claude/dispatch-logs/）。
function run(slot, number, kind) {
  const dir = slotDir(slot);
  const logs = join(root, ".claude", "dispatch-logs");
  mkdirSync(logs, { recursive: true });
  const out = openSync(join(logs, `${slot}-${number}-${Date.now()}.log`), "a");
  const prompt = [
    `あなたは RideCompass の${kind}担当です。作業ツリー ${dir} で、置き場 ${config.repository} の issue #${number} を扱います。`,
    `まず ${dir} の CLAUDE.md と docs/conventions/flow.md の「司令塔と担当」「${kind}担当」「問い」「issue の形」を読み、その手順のとおりに進めてください。`,
    "作業はこの作業ツリーの中だけで行い、終わるときは手順のとおり push と issue への報告をして終えてください。",
    "鍵・スロット・次の振り出しの後始末は起動役がするので、触れないでください。すべて日本語で書いてください。",
  ].join("\n");
  return new Promise((resolve) => {
    const child = spawn("claude", ["-p", prompt, "--permission-mode", "auto", "--permission-prompts", "none"], {
      cwd: dir,
      stdio: ["ignore", out, out],
      windowsHide: true,
    });
    child.on("error", (e) => (log(`担当を起こせなかった: ${e.message}`), resolve(-1)));
    child.on("exit", (code) => resolve(code ?? -1));
  });
}

// 後始末。作る担当の issue が振り出した状態（進行中）のままなら、Pull Request も問いも出さずに終わったので落ちたとみなす。
async function finish(slot, number, kind, why, next = true) {
  const dir = slotDir(slot);
  const found = [];
  if (kind === "作る") {
    const { issue } = await readTask(new GitHub(botToken()), config, { number });
    const doing = config.transitions.find((t) => t.on === "振り出し").to[0];
    if (issue?.state === "OPEN" && issue.status === doing) {
      log(tool("move.js", String(number), "落ちた", `スロット ${slot} の作る担当が、Pull Request も問いも出さずに終わった（${why}）`));
      found.push(`スロット ${slot} の作る担当（#${number}）が Pull Request も問いも出さずに終わったので保留にした（${why}）`);
    }
  }
  if (git(dir, "status", "--porcelain") === "") {
    git(dir, "checkout", "-q", "--detach");
    git(dir, "worktree", "unlock", dir);
    log(`スロット ${slot} の鍵を外した（${why}）`);
  } else found.push(`スロット ${slot}（#${number} の${kind}担当）に未コミットの変更が残っているので、鍵ごと残した（${why}）`);
  log(tool("status.js", ...found.flatMap((f) => ["--found", f])));
  if (next) log(tool("dispatch.js"));
}
