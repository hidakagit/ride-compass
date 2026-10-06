// 担当のワークフロー（.github/workflows/claude-task.yml）の後始末。担当が落ちても止められても走る。終わり方（src/after.js: settle）で、
// 利用の上限・認証なら振り出しを止め（コードのリポジトリの変数 coordinator.pauseVariable に止める時刻を置く）、作る担当のタスクが
// 進行中のままなら動かし（作業ブランチの開いた Pull Request があれば検証中へ）、どちらの担当でも手番の記録を置き場のリリースへ置いて、issue に終わりを書く。
import { existsSync, readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { endReport, keepLog, settle } from "../src/after.js";
import { readTask } from "../src/github.js";
import { moveTask } from "../src/move.js";
import { notes } from "../src/rules.js";
import { args, bot, code, config, isNumber } from "./cli.js";

const { dry, rest: [number, kind, file, url, jobStatus] } = args("node tools/flow-gate/bin/after.js [--dry-run] <issue の番号> <作る|確かめる> <実行のファイル（無ければ空）> <実行の URL> <ジョブの結果>",
  (a) => a.length === 5 && isNumber(a[0]) && ["作る", "確かめる"].includes(a[1]));
const raw = file && existsSync(file) ? readFileSync(file) : null;
const messages = raw ? JSON.parse(raw.toString("utf8")) : null;
const gh = bot();
const repo = code();
const done = [];
const note = (line) => (console.log(`${dry ? "（試し）" : ""}${line}`), done.push(line));
const task = (await readTask(gh, config, { number: Number(number) })).issue;
const moves = kind === "作る" && task?.status === config.working;
const { repository, branchPrefix } = config.code;
const head = `${repository.split("/")[0]}:${branchPrefix}${number}`;
const [pullRequest = null] = moves ? await repo.rest("GET", `/repos/${repository}/pulls?state=open&head=${encodeURIComponent(head)}`)
  .catch((e) => (note(`開いた Pull Request を読めなかった（${e.message}）`), [])) : [];
const step = settle(config, { messages, startOn: task?.fields[config.project.startField], labels: task?.labels.nodes.map((l) => l.name) ?? [],
  blockers: (task?.blockedBy.nodes ?? []).filter((b) => b.state !== "CLOSED").map((b) => b.number), pullRequest, url, jobStatus });

if (step.pause) {
  const { pauseVariable: name, pauseMinutes } = config.coordinator;
  const until = new Date(Date.now() + pauseMinutes * 60e3).toISOString();
  const path = `/repos/${config.code.repository}/actions/variables`;
  note(dry ? `振り出しを ${until} まで止めた` : await repo.rest("PATCH", `${path}/${name}`, { name, value: until })
    .catch(() => repo.rest("POST", path, { name, value: until }))
    .then(() => `振り出しを ${until} まで止めた`, (e) => `振り出しを止められなかった（${e.message}）`));
}
if (moves)
  note(await moveTask(gh, config, Number(number), step.to, { comment: notes.reason(step.to, step.reason), dryRun: dry }).catch((e) => `${step.to}へ動かさなかった（${e.message}）`));
else note(`${task?.status ?? "置き場に無い"}なので動かさなかった`);

if (raw && !dry) {
  const name = `tasks-${number}-${url.split("/").pop()}-${new Date().toISOString().replace(/\D/g, "").slice(0, 14)}.json.gz`;
  note(await keepLog(gh, config.repository, { gz: gzipSync(raw), name }).then((link) => `手番の記録を置いた: ${link}`, (e) => `手番の記録を置けなかった（${e.message}）`));
} else note(raw ? "手番の記録を置き場のリリースへ置く" : "手番の記録は無い（実行のファイルが無い）");

const body = endReport({ kind, url, messages, done });
if (dry) console.log(body);
else await gh.rest("POST", `/repos/${config.repository}/issues/${number}/comments`, { body });
