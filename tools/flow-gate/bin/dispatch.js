// 振り出しの見回りの1周（繰り返しは .github/workflows/claude-dispatch.yml が、1周ごとに master の今の道具で打つ）。種類ごとの枠まで
// 担当のワークフローを起こし、全体の様子を Project の状況の更新に書く。持つ印（src/hold.js）のあるタスクは振り出さない。
// 見回りのワークフローが無効なら振り出さずに書き、終わりの値 3 で終える。後始末が置いた止める時刻が先なら振り出さない。
import { pick, putStatus, readActive, readTasks, ready, runOf, staleHolds, startRun, summary, workload } from "../src/dispatch.js";
import { readHolds, release } from "../src/hold.js";
import { args, bot, code, config, holds } from "./cli.js";

const { dry } = args("node tools/flow-gate/bin/dispatch.js [--dry-run]", (a) => !a.length);
const say = (line) => console.log(`${dry ? "（試し）" : ""}${line}`);
const { workflow, watcher, pauseVariable } = config.coordinator;
const { repository } = config.code;
const gh = bot();
const repo = code();
const env = process.env;

// 持つ印は、動いている実行より先に読む（src/dispatch.js: staleHolds）。
const remote = holds();
const held = await readHolds(remote, config);
// 動いている担当は終わっていない実行を全部読んで数え、状況の更新の失敗は新しい100件から見る。どの読みも互いに依らないので並べる。
const [wf, variable, active, { workflow_runs: recent }, board] = await Promise.all([
  repo.rest("GET", `/repos/${repository}/actions/workflows/${watcher}`),
  repo.rest("GET", `/repos/${repository}/actions/variables/${pauseVariable}`).catch(() => null),
  readActive((path) => repo.rest("GET", path), config),
  repo.rest("GET", `/repos/${repository}/actions/workflows/${workflow}/runs?per_page=100`),
  readTasks(gh, config, "is:open"),
]);
const stopped = wf.state !== "active";
const pause = variable && Date.parse(variable.value) > Date.now() ? variable.value : null;
const runs = [...new Map([...recent, ...active].map((r) => [r.id, r])).values()]
  .sort((a, b) => b.created_at.localeCompare(a.created_at))
  .map((r) => {
    const [n, kind] = runOf(r.display_title);
    return { number: Number(n), kind, url: r.html_url, conclusion: r.status === "completed" ? r.conclusion : null };
  })
  .filter((r) => r.number);
const running = runs.filter((r) => !r.conclusion);
// 実行が終わったのに残った担当の印は消す（前の値つきで消すので、その間に取り直された印は消さない）。
const stale = staleHolds(config, held, active.map((r) => r.html_url));
for (const h of stale) {
  say(`#${h.number} の印（${h.who}）は実行が終わっているので消す`);
  if (!dry) await release(remote, config, h.number, h.who).catch((e) => say(`#${h.number} の印を消せなかった（${e.message}）`));
}
board.tasks = board.tasks.map((t) => ({ ...t, held: held.find((h) => h.number === t.number && !stale.includes(h))?.who ?? null }));
const candidates = ready(config, board, running);
const open = pick(config, candidates, running);
const started = stopped || pause ? [] : open;
for (const t of started) {
  say(`#${t.number} を${t.kind}担当として起こす`);
  if (!dry) await startRun(repo, config, t.number, t.kind);
}
const idle = !open.length ? null : stopped ? "見回りのワークフローが無効（Actions の画面で Enable workflow のあと Run workflow で戻す）" : pause ? `${pause} まで止めている（利用の上限など）` : null;
const load = await workload(gh, config, board.tasks);
if (dry) say(`作業時間: ${load.tasks.map((t) => `#${t.number}（${t.size}）${t.workHours.toFixed(2)}時間`).join("・") || "無し"} ／ 想定: ${Object.entries(load.expected).map(([size, h]) => `${size} ${h.toFixed(2)}時間`).join("・") || "無し"}`);
const status = summary(config, {
  watcher: env.GITHUB_RUN_ID ? `[実行](${env.GITHUB_SERVER_URL}/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID})` : "手元の試し",
  tasks: board.tasks, working: load.tasks, expected: load.expected, runs, started, waiting: candidates.length - started.length, idle,
});
if (dry) say(`状況の更新（${status.status}）:\n${status.body}`);
else if (await putStatus(gh, config, status)) say(`状況の更新を書いた（${status.status}）`);
if (stopped) process.exit(3);
