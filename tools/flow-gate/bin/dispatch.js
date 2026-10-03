// 振り出し。担当のワークフロー（coordinator.workflow）を、動いている数が coordinator.parallel になるまで、キューの上から起こす。
// --watch では、1つの実行の中で coordinator.watchEveryMinutes ごとに振り出しを繰り返し（見回り）、全体の様子を Project の
// 状況の更新に書く。coordinator.watchForMinutes が過ぎたら終える（次の見回りは .github/workflows/claude-dispatch.yml が起こす）。
// 何か所から同時に起きても、担当のワークフローの最初の段（作るなら振り出しの遷移が通るか、確かめるなら検証中か）が二重の作業を止める。
// 止めの印（ラベル coordinator.stopLabel）が置き場の開いた issue にあるか、利用の上限などで止めた時刻（coordinator.pauseVariable）
// までは、何も起こさない（見回りは続ける）。
// 使い方: node tools/flow-gate/bin/dispatch.js [--dry-run] [--watch]（--dry-run は何を起こすか・何を書くかを出すだけで、何も起こさない）
import { setTimeout as sleep } from "node:timers/promises";
import config from "../flow.config.json" with { type: "json" };
import { dated, pick, queueOf, readBoard, ready, runIssue, stuck, summary } from "../src/dispatch.js";
import { GitHub } from "../src/github.js";
import { putStatus } from "../src/status.js";
import { botToken, codeToken } from "./token.js";

const args = process.argv.slice(2);
if (args.some((a) => !["--dry-run", "--watch"].includes(a))) {
  console.error("使い方: node tools/flow-gate/bin/dispatch.js [--dry-run] [--watch]");
  process.exit(2);
}
const dry = args.includes("--dry-run");
const watch = args.includes("--watch");
const say = (line) => console.log(`${dry ? "（試し）" : ""}${line}`);
const { stopLabel, workflow, pauseVariable, watchEveryMinutes, watchForMinutes } = config.coordinator;
const { repository, base, branchPrefix } = config.code;
const [o, n] = config.repository.split("/");
const bot = new GitHub(botToken());
const code = new GitHub(codeToken());
const env = process.env;
const watcher = env.GITHUB_RUN_ID ? `${env.GITHUB_SERVER_URL}/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID}` : null;

// 1周。seen は前の周で止まっているように見えた番号。止まっているものは、2周続けて見えたものだけを書く（Pull Request を出した直後など、
// 担当が終わってからゲートがステータスを動かすまでの間を、止まっていると見ないため）。今の周で見えた番号を返す。
async function round(seen) {
  const s = await bot.gql(
    `query Stop($o: String!, $n: String!, $l: [String!]) { repository(owner: $o, name: $n) { issues(states: OPEN, labels: $l, first: 1) { nodes { number } } } }`,
    { o, n, l: [stopLabel] },
  );
  const stop = s.repository.issues.nodes[0]?.number ?? null;
  // 止める時刻は後始末（bin/after.js）がリポジトリの変数に置く。
  const variable = await code.rest("GET", `/repos/${repository}/actions/variables/${pauseVariable}`).catch(() => null);
  const pause = variable && Date.parse(variable.value) > Date.now() ? variable.value : null;
  // 動いている担当: 担当のワークフローの実行のうち、終わっていないもの（待っているものを含む）。
  const all = await code.rest("GET", `/repos/${repository}/actions/workflows/${workflow}/runs?per_page=100`);
  const runs = all.workflow_runs
    .filter((r) => r.status !== "completed" && runIssue(r.display_title))
    .map((r) => ({ number: runIssue(r.display_title), title: r.display_title, url: r.html_url, startedAt: r.run_started_at ?? r.created_at }))
    .sort((a, b) => a.number - b.number);
  const running = new Set(runs.map((r) => r.number));
  const board = await readBoard(bot, config);
  const queue = queueOf(config, board);

  const chosen = stop || pause ? [] : pick(config, queue, running);
  if (stop) say(`#${stop} にラベル「${stopLabel}」が付いているので、振り出さない`);
  else if (pause) say(`${pause} まで振り出しを止めている（リポジトリの変数 ${pauseVariable}）`);
  else if (!chosen.length) say(`振り出すものは無い（動いている担当 ${running.size}）`);
  for (const t of chosen) {
    say(`#${t.number}（${t.status}）を${t.kind}担当として起こす`);
    if (!dry) await code.rest("POST", `/repos/${repository}/actions/workflows/${workflow}/dispatches`, { ref: base, inputs: { issue: String(t.number), kind: t.kind } });
  }
  if (!watch) return new Set();

  const prs = await code.rest("GET", `/repos/${repository}/pulls?state=open&per_page=100`);
  const open = new Set(prs.map((p) => p.head.ref).filter((ref) => ref.startsWith(branchPrefix)));
  const now = stuck(config, board.tasks, running, open);
  const waiting = ready(config, queue, running).length;
  const later = dated(queue, running).map((t) => t.startOn);
  const status = summary(config, {
    watcher,
    runs,
    started: chosen,
    waiting: waiting - chosen.length,
    held: queue.filter((t) => !running.has(t.number)).length - waiting - later.length,
    dated: later,
    stuck: now.filter((t) => seen.has(t.number)),
    stop,
    pause,
  });
  if (dry) say(`状況の更新（${status.status}）:\n${status.body}`);
  else {
    const wrote = await putStatus(bot, config, status);
    if (wrote) say(`状況の更新を${wrote === "created" ? "足した" : "書き換えた"}（${status.status}）`);
  }
  return new Set(now.map((t) => t.number));
}

if (!watch) await round(new Set());
else {
  const end = Date.now() + watchForMinutes * 60000;
  let seen = new Set();
  while (Date.now() < end) {
    try {
      seen = await round(seen);
    } catch (e) {
      // 1周の失敗（GitHub の一時の失敗など）で見回りを止めない。
      console.error(`見回りの1周に失敗: ${e.message}`);
    }
    await sleep(Math.max(0, Math.min(watchEveryMinutes * 60000, end - Date.now())));
  }
  say(`${watchForMinutes}分の見回りを終える`);
}
