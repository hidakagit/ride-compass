// 担当のワークフロー（.github/workflows/claude-task.yml）の後始末。担当が落ちても止められても走る。
// 担当の外の失敗（src/after.js: classify）なら、作る担当のタスクを未着手へ戻し（戻す）、利用の上限・認証なら振り出しを
// coordinator.pauseMinutes の間止める（リポジトリの変数 coordinator.pauseVariable に止める時刻を置く。振り出しが読む）。
// それ以外で作る担当のタスクが進行中のまま（PR も問いも出さずに終わった）なら、落ちたとみなして保留にする。ただし開いた子の
// 段階があれば、段階に分けて終えたので進行中のまま置き、着手可能日が先なら、その日まで待つので未着手へ戻す（src/after.js: settle）。
// 最後に、終わり方・かかった時間・手数・担当の最後の発言を issue へ書く（src/after.js: endReport）。発言は記録に出さない。
// （--dry-run は本物の GitHub を読み、止める時刻・動かす遷移・書くはずのコメントを出すだけで、書かない）
// 使い方: node tools/flow-gate/bin/after.js [--dry-run] <issue の番号> <作る|確かめる> <実行のファイル（無ければ空）> <実行の URL> <ジョブの結果>
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import config from "../flow.config.json" with { type: "json" };
import { classify, endReport, refusal, settle } from "../src/after.js";
import { GitHub, readTask } from "../src/github.js";
import { botToken, codeToken } from "./token.js";

const dry = process.argv[2] === "--dry-run";
const [number, kind, file, url, status, ...rest] = process.argv.slice(dry ? 3 : 2);
if (!/^\d+$/.test(number ?? "") || !["作る", "確かめる"].includes(kind) || rest.length) {
  console.error("使い方: node tools/flow-gate/bin/after.js [--dry-run] <issue の番号> <作る|確かめる> <実行のファイル> <実行の URL> <ジョブの結果>");
  process.exit(2);
}
const here = dirname(fileURLToPath(import.meta.url));
const messages = file && existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : null;
// 持ち時間を超えた・手で Cancel された（ジョブの結果 cancelled）は担当の側の止まりなので、上限と見分けて落ちたとして扱う。
const verdict = status === "cancelled" ? { outside: false, pause: false, reason: "" } : classify(messages);
const done = [];
const note = (line) => {
  console.log(dry && !line.startsWith("（試し）") ? `（試し）${line}` : line);
  done.push(line);
};
const move = (to, reason) => {
  try {
    note(execFileSync(process.execPath, [join(here, "move.js"), ...(dry ? ["--dry-run"] : []), number, to, reason], { encoding: "utf8" }).trim());
  } catch (e) {
    note(`${to}へ動かさなかった（${refusal(e)}）`);
  }
};
const code = new GitHub(codeToken());

if (verdict.pause) {
  const { pauseVariable, pauseMinutes } = config.coordinator;
  const until = new Date(Date.now() + pauseMinutes * 60000).toISOString();
  const path = `/repos/${config.code.repository}/actions/variables`;
  if (!dry) {
    try {
      await code.rest("PATCH", `${path}/${pauseVariable}`, { name: pauseVariable, value: until });
    } catch {
      await code.rest("POST", path, { name: pauseVariable, value: until });
    }
  }
  note(`振り出しを ${until} まで止めた（${verdict.reason}）`);
}
const bot = new GitHub(botToken());
if (kind === "作る") {
  const { issue: task } = await readTask(bot, config, { number: Number(number) });
  const step = task?.status === config.working
    ? settle(config, { verdict, children: task.subIssues.nodes, startOn: task.fields[config.project.startField] ?? null, url, jobStatus: status })
    : null;
  if (step) move(step.to, step.reason);
  else note(task?.status === config.working ? "開いた子の段階があるので、進行中のまま置いた（段階に分けて終えた）" : `${task?.status ?? "置き場に無い"}なので動かさなかった（担当が PR か問いを出した）`);
}

const { issue } = await readTask(bot, config, { number: Number(number) });
const run = await code.rest("GET", `/repos/${config.code.repository}/actions/runs/${url.split("/").at(-1)}`).catch(() => null);
const elapsedMs = run?.run_started_at ? Date.now() - Date.parse(run.run_started_at) : null;
const body = endReport({ kind, url, jobStatus: status, messages, done, status: issue?.status, elapsedMs });
if (dry) console.log(`（試し）#${number} へ書く終わり（ステータスは今のもの）:
${body}`);
else {
  await bot.rest("POST", `/repos/${config.repository}/issues/${number}/comments`, { body });
  console.log(`#${number} へ終わりを書いた（担当の発言は記録に出さない）`);
}
