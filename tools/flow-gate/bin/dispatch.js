// 司令塔。振り出すだけをする: 空いたスロットを数え、止めの印が無ければ、GitHub のステータスから導いたキューの上から、
// 空いたスロットに鍵を掛けて起動役（work.js）を切り離して起こす。担当の後始末・状況の更新は起動役がする。
// 起こすのは、担当が終わったとき（起動役が呼ぶ）と、OS のタスク スケジューラの定期の起動（取りこぼしを拾う）。
// 何か所から同時に起こしても、スロットの鍵（slots.js take）が二重の振り出しを防ぐ。
// 起動役ごと消えたスロットは、空きを数える前に起動役の後始末（work.js --finish）へ渡す。止めの印が
// あってもこれはする（止めている間に手で止めた担当を、保留にして鍵を外すため）。
// 使い方: node tools/flow-gate/bin/dispatch.js [--dry-run]（--dry-run は何をするかを出すだけで、何も書かない）
import { execFileSync, spawn } from "node:child_process";
import { mkdirSync, openSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import config from "../flow.config.json" with { type: "json" };
import { GitHub } from "../src/github.js";
import { botToken } from "./token.js";

const args = process.argv.slice(2);
if (args.some((a) => a !== "--dry-run")) {
  console.error("使い方: node tools/flow-gate/bin/dispatch.js [--dry-run]");
  process.exit(2);
}
const dry = args.includes("--dry-run");
const here = dirname(fileURLToPath(import.meta.url));
const node = (script, ...rest) => execFileSync(process.execPath, [join(here, script), ...rest], { encoding: "utf8" }).trim();
const ok = (script, ...rest) => {
  try {
    node(script, ...rest);
    return true;
  } catch {
    return false;
  }
};
const say = (line) => console.log(`${dry ? "（試し）" : ""}${line}`);
const root = join(execFileSync("git", ["-C", here, "rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8" }).trim(), "..");

// 起動役は担当を持ち時間（dropMinutes）で止めて後始末をするので、abandonMinutes を超えて残る鍵の起動役も居ない（pid が別の
// プロセスに使い回されて生きて見えるとき・pid を足す前に起動役が消えたときも、これで拾う）。
const { abandonMinutes } = config.coordinator;
const gone = (s) => s.state === "使用中" && s.number && ((s.pid && !s.alive) || s.minutes > abandonMinutes);
for (const s of JSON.parse(node("slots.js", "--json")).filter(gone)) {
  say(`スロット ${s.slot} の起動役${s.pid ? `（pid ${s.pid}）` : ""}が${s.pid && !s.alive ? "居ない" : `、鍵を掛けてから ${abandonMinutes} 分を超えても後始末をしていない`}ので、後始末へ渡す`);
  if (dry) continue;
  try {
    console.log(node("work.js", "--finish", s.slot, "--no-dispatch"));
  } catch (e) {
    console.log(`スロット ${s.slot} の後始末に失敗: ${String(e.stderr || e.message).trim()}`);
  }
}

// 止めの印: 置き場の開いた issue のどれかにラベル「停止」が付いていれば、振り出さない（スマホからでも止められる）。
const [o, n] = config.repository.split("/");
const stop = await new GitHub(botToken()).gql(
  `query Stop($o: String!, $n: String!, $l: [String!]) { repository(owner: $o, name: $n) { issues(states: OPEN, labels: $l, first: 1) { nodes { number } } } }`,
  { o, n, l: [config.coordinator.stopLabel] },
);
if (stop.repository.issues.nodes[0]) {
  say(`#${stop.repository.issues.nodes[0].number} にラベル「${config.coordinator.stopLabel}」が付いているので、振り出さない`);
  process.exit(0);
}

const slots = JSON.parse(node("slots.js", "--json"));
const busy = new Set(slots.filter((s) => s.number).map((s) => s.number));
const queue = JSON.parse(node("queue.js", "--json")).filter((t) => !busy.has(t.number) && !t.waitingFor.length);
const todo = config.transitions.find((t) => t.on === "振り出し").from[0];
for (const s of slots.filter((s) => s.state === "空き")) {
  const t = queue.shift();
  if (!t) break;
  const kind = t.status === todo ? "作る" : "確かめる";
  say(`スロット ${s.slot} へ #${t.number}（${t.status}）を${kind}担当として振り出す`);
  if (dry) continue;
  if (!ok("slots.js", "take", s.slot, String(t.number), kind)) continue;
  if (kind === "作る" && !ok("move.js", String(t.number), "振り出し")) {
    execFileSync("git", ["-C", root, "worktree", "unlock", join(root, ".claude", "worktrees", s.slot)]);
    continue;
  }
  // 起動役の出力は .claude/dispatch-logs/ に残す（担当の出力とは別のファイル）。
  const logs = join(root, ".claude", "dispatch-logs");
  mkdirSync(logs, { recursive: true });
  const out = openSync(join(logs, `work-${s.slot}-${t.number}-${Date.now()}.log`), "a");
  spawn(process.execPath, [join(here, "work.js"), s.slot, String(t.number), kind], { detached: true, stdio: ["ignore", out, out], windowsHide: true }).unref();
}
