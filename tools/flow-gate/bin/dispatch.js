// 振り出し。担当のワークフロー（coordinator.workflow）を、動いている数が coordinator.parallel になるまで、キューの上から起こす。
// --watch では、1つの実行の中で coordinator.watchEveryMinutes ごとに振り出しを繰り返し（見回り）、全体の様子を Project の
// 状況の更新に書く。coordinator.watchForMinutes が過ぎたら終える（次の見回りは .github/workflows/claude-dispatch.yml が起こす）。
// 何か所から同時に起きても、担当のワークフローの最初の段（作るなら振り出しの遷移が通るか、確かめるなら検証中か）が二重の作業を止める。
// 利用の上限などで止める時刻（coordinator.pauseVariable）が先なら振り出さない。見回りのワークフローが無効（Actions の画面の
// Disable workflow）なら、状況の更新に止めていると書いて見回りを終える。
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
const { workflow, pauseVariable, watchEveryMinutes, watchForMinutes } = config.coordinator;
const { repository, base, branchPrefix } = config.code;
const bot = new GitHub(botToken());
const code = new GitHub(codeToken());
const env = process.env;
const watcher = env.GITHUB_RUN_ID ? `${env.GITHUB_SERVER_URL}/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID}` : null;

// 1周。seen は前の周で止まっているように見えた番号。止まっているものは、2周続けて見えたものだけを書く（Pull Request を出した直後など、
// 担当が終わってからゲートがステータスを動かすまでの間を、止まっていると見ないため）。今の周で見えた番号を返す。
async function round(seen) {
  // 見回り自身のワークフロー（Actions の中で動いているときだけ分かる）が無効なら、止める。
  const self = process.env.GITHUB_WORKFLOW_REF?.match(/\.github\/workflows\/([^@]+)@/)?.[1];
  const stop = self ? (await code.rest("GET", `/repos/${repository}/actions/workflows/${self}`)).state !== "active" : false;
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
  if (stop) say("見回りのワークフローが無効なので、振り出さずに見回りを終える");
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
  // 止めたら null を返し、見回りを終える。
  return stop ? null : new Set(now.map((t) => t.number));
}

if (!watch) await round(new Set());
else {
  const end = Date.now() + watchForMinutes * 60000;
  let seen = new Set();
  while (Date.now() < end) {
    try {
      const next = await round(seen);
      if (next === null) break;
      seen = next;
    } catch (e) {
      // 1周の失敗（GitHub の一時の失敗など）で見回りを止めない。
      console.error(`見回りの1周に失敗: ${e.message}`);
    }
    await sleep(Math.max(0, Math.min(watchEveryMinutes * 60000, end - Date.now())));
  }
  say(`${watchForMinutes}分の見回りを終える`);
}
