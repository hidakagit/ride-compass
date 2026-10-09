// 担当のワークフロー（.github/workflows/claude-task.yml）の後始末。担当が落ちても止められても走る。終わり方（src/after.js: settle）で、
// 利用の上限・認証なら振り出しを止め（コードのリポジトリの変数 coordinator.pauseVariable に止める時刻を置き）、作る担当のタスクが
// 進行中のままなら未着手へ戻して、issue に終わりを書く。
import { existsSync, readFileSync } from "node:fs";
import { endReport, settle } from "../src/after.js";
import { readTask } from "../src/github.js";
import { moveTask } from "../src/move.js";
import { notes } from "../src/rules.js";
import { args, bot, code, config, isNumber } from "./cli.js";

const { dry, rest: [number, kind, file, url, jobStatus] } = args("node tools/flow-gate/bin/after.js [--dry-run] <issue の番号> <作る|確かめる> <実行のファイル（無ければ空）> <実行の URL> <ジョブの結果>",
  (a) => a.length === 5 && isNumber(a[0]) && ["作る", "確かめる"].includes(a[1]));
const messages = file && existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : null;
const gh = bot();
const done = [];
const note = (line) => (console.log(line), done.push(line));
const task = (await readTask(gh, config, { number: Number(number) })).issue;
const step = settle({ messages, url, jobStatus });

if (step.pause) {
  const repo = code();
  const { pauseVariable: name, pauseMinutes } = config.coordinator;
  const until = new Date(Date.now() + pauseMinutes * 60e3).toISOString();
  const path = `/repos/${config.code.repository}/actions/variables`;
  note(dry ? `（試し）振り出しを ${until} まで止めた` : await repo.rest("PATCH", `${path}/${name}`, { name, value: until })
    .catch(() => repo.rest("POST", path, { name, value: until }))
    .then(() => `振り出しを ${until} まで止めた`, (e) => `振り出しを止められなかった（${e.message}）`));
}
if (kind === "作る" && task?.status === config.working)
  note(await moveTask(gh, config, Number(number), config.todo, { comment: notes.reason(config.todo, step.reason), dryRun: dry }).catch((e) => `${config.todo}へ動かさなかった（${e.message}）`));
else note(`${task?.status ?? "置き場に無い"}なので動かさなかった`);

const body = endReport({ kind, url, messages, done });
if (dry) console.log(body);
else await gh.rest("POST", `/repos/${config.repository}/issues/${number}/comments`, { body });
