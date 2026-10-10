// 見回りの1周（繰り返しは .github/workflows/claude-dispatch.yml が、1周ごとに master の今の道具で打つ）。種類ごとの枠まで担当の
// ワークフローを起こし、ボードと担当の実行が食い違うタスクはゲートに決め直しを頼む（置き場への repository_dispatch「recheck」）。
// 見回りのワークフローが無効なら振り出さずに終わりの値 3 で終える。後始末が置いた止める時刻が先なら振り出さない。
import { readActive } from "../src/github.js";
import { mismatches, pick, readTasks, ready, startRun } from "../src/dispatch.js";
import { args, bot, code, config } from "./cli.js";

const { dry } = args("node tools/flow-gate/bin/dispatch.js [--dry-run]", (a) => !a.length);
const say = (line) => console.log(`${dry ? "（試し）" : ""}${line}`);
const { watcher, pauseVariable } = config.coordinator;
const { repository, branchPrefix } = config.code;
const gh = bot();
const repo = code();

const [wf, variable, active, board] = await Promise.all([
  repo.rest("GET", `/repos/${repository}/actions/workflows/${watcher}`),
  repo.rest("GET", `/repos/${repository}/actions/variables/${pauseVariable}`).catch(() => null),
  readActive((path) => repo.rest("GET", path), config),
  readTasks(gh, config, "is:open"),
]);
const stopped = wf.state !== "active";
const pause = variable && Date.parse(variable.value) > Date.now() ? variable.value : null;
const running = active.filter((r) => r.number);

// CI待ちのタスクのうち、作業ブランチの CI の実行が1つも動いていないもの。
const ciIdle = new Set();
for (const t of board.tasks.filter((t) => t.status === config.status.ci)) {
  const { workflow_runs: runs } = await repo.rest("GET", `/repos/${repository}/actions/runs?branch=${encodeURIComponent(`${branchPrefix}${t.number}`)}&per_page=30`);
  if (runs.every((r) => r.status === "completed")) ciIdle.add(t.number);
}
for (const number of mismatches(config, board.tasks, running, ciIdle)) {
  say(`#${number} のボードと担当の実行が食い違うので、ゲートに決め直しを頼む`);
  if (!dry) await gh.rest("POST", `/repos/${config.repository}/dispatches`, { event_type: "recheck", client_payload: { number } });
}

const open = pick(config, ready(config, board, running), running);
if (stopped) say("見回りのワークフローが無効なので振り出さない（Actions の画面で Enable workflow のあと Run workflow で戻す）");
else if (pause && open.length) say(`${pause} まで振り出しを止めている（利用の上限など）`);
else for (const t of open) {
  say(`#${t.number} を${t.kind}担当として起こす`);
  if (!dry) await startRun(repo, config, t.number, t.kind);
}
if (stopped) process.exit(3);
