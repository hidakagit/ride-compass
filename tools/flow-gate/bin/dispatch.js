// 振り出しの見回りの1周（繰り返しは .github/workflows/claude-dispatch.yml が、1周ごとに master の今の道具で打つ）。種類ごとの枠まで
// 担当のワークフローを起こし、全体の様子（本番の管理データのバックアップの止まりも）を Project の状況の更新に書く。同じタスクの担当は、担当のワークフローのグループで1本ずつ動く。
// 見回りのワークフローが無効なら振り出さずに書き、終わりの値 3 で終える。後始末が置いた止める時刻が先なら振り出さない。
import { pick, putStatus, readBackup, readTasks, ready, runOf, summary, workload } from "../src/dispatch.js";
import { args, bot, code, config } from "./cli.js";

const { dry } = args("node tools/flow-gate/bin/dispatch.js [--dry-run]", (a) => !a.length);
const say = (line) => console.log(`${dry ? "（試し）" : ""}${line}`);
const { workflow, watcher, pauseVariable } = config.coordinator;
const { repository, base } = config.code;
const gh = bot();
const repo = code();
const env = process.env;

const stopped = (await repo.rest("GET", `/repos/${repository}/actions/workflows/${watcher}`)).state !== "active";
const variable = await repo.rest("GET", `/repos/${repository}/actions/variables/${pauseVariable}`).catch(() => null);
const pause = variable && Date.parse(variable.value) > Date.now() ? variable.value : null;
const runs = (await repo.rest("GET", `/repos/${repository}/actions/workflows/${workflow}/runs?per_page=100`)).workflow_runs
  .map((r) => ({ number: Number(runOf(r.display_title)[0]), kind: runOf(r.display_title)[1], url: r.html_url, conclusion: r.status === "completed" ? r.conclusion : null }))
  .filter((r) => r.number);
const running = runs.filter((r) => !r.conclusion);
const board = await readTasks(gh, config, "is:open");
const candidates = ready(config, board, running);
const open = pick(config, candidates, running);
const started = stopped || pause ? [] : open;
for (const t of started) {
  say(`#${t.number} を${t.kind}担当として起こす`);
  if (!dry) await repo.rest("POST", `/repos/${repository}/actions/workflows/${workflow}/dispatches`, { ref: base, inputs: { issue: String(t.number), kind: t.kind } });
}
const idle = !open.length ? null : stopped ? "見回りのワークフローが無効（Actions の画面で Enable workflow のあと Run workflow で戻す）" : pause ? `${pause} まで止めている（利用の上限など）` : null;
const load = await workload(gh, config, board.tasks, (await readTasks(gh, config, "is:closed reason:completed")).tasks);
if (dry) {
  for (const t of load.tasks) say(`#${t.number}（${t.status}・${t.size ?? "規模なし"}）の作業時間 ${t.workHours.toFixed(2)}時間`);
  say(`想定: ${Object.entries(load.expected).map(([size, h]) => `${size} ${h.toFixed(2)}時間`).join("・") || "無し"}`);
}
const status = summary(config, {
  watcher: env.GITHUB_RUN_ID ? `[実行](${env.GITHUB_SERVER_URL}/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID})` : "手元の試し",
  tasks: board.tasks, working: load.tasks, expected: load.expected, runs, started, waiting: candidates.length - started.length, idle,
  backup: await readBackup(repo, config),
});
if (dry) say(`状況の更新（${status.status}）:\n${status.body}`);
else if (await putStatus(gh, config, status)) say(`状況の更新を書いた（${status.status}）`);
if (stopped) process.exit(3);
