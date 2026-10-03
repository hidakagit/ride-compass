// 振り出しの見回りの1周。担当のワークフロー（coordinator.workflow）を、種類ごとに動いている数が coordinator.parallel になるまで、
// キューの上から起こし、全体の様子を Project の状況の更新に書く。周の繰り返しは .github/workflows/claude-dispatch.yml が持ち、
// 1周ごとに master を取り出し直してこれを打つ。
// 何か所から同時に起きても、担当のワークフローの最初の段（作るなら振り出しの遷移が通るか、確かめるなら検証中か）が二重の作業を止める。
// 利用の上限などで止める時刻（coordinator.pauseVariable）が先なら振り出さない。見回りのワークフローが無効（Actions の画面の
// Disable workflow）なら、状況の更新に止めていると書いて終わり方 3 で終える（見回りの繰り返しが止まる）。
// 落ちた実行は、環境変数 DISPATCH_SINCE（前の周を始めた時刻。無ければ coordinator.watchEveryMinutes 前）の後に失敗で終わったものを出す。
// 使い方: node tools/flow-gate/bin/dispatch.js [--dry-run]（--dry-run は何を起こすか・何を書くかを出すだけで、何も起こさない）
import { readFileSync } from "node:fs";
import config from "../flow.config.json" with { type: "json" };
import { dated, free, pick, queueOf, readBoard, ready, runIssue, stuck, summary } from "../src/dispatch.js";
import { GitHub } from "../src/github.js";
import { putStatus } from "../src/status.js";
import { botToken, codeToken } from "./token.js";

const args = process.argv.slice(2);
if (args.some((a) => a !== "--dry-run")) {
  console.error("使い方: node tools/flow-gate/bin/dispatch.js [--dry-run]");
  process.exit(2);
}
const dry = args.includes("--dry-run");
const say = (line) => console.log(`${dry ? "（試し）" : ""}${line}`);
const { workflow, pauseVariable, watchEveryMinutes } = config.coordinator;
const { repository, base } = config.code;
const bot = new GitHub(botToken());
const code = new GitHub(codeToken());
const env = process.env;
const watcher = env.GITHUB_RUN_ID ? `${env.GITHUB_SERVER_URL}/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID}` : null;
const since = env.DISPATCH_SINCE ? Date.parse(env.DISPATCH_SINCE) : Date.now() - watchEveryMinutes * 60000;
// 担当の持ち時間は担当のワークフローのジョブの timeout-minutes で、設定に写さない。
const timeoutMinutes = Number(/timeout-minutes:\s*(\d+)/.exec(readFileSync(new URL(`../../../.github/workflows/${workflow}`, import.meta.url), "utf8"))?.[1]);
if (!timeoutMinutes) throw new Error(`${workflow} に timeout-minutes が無い`);

// 見回り自身のワークフロー（Actions の中で動いているときだけ分かる）が無効なら、止める。
const self = env.GITHUB_WORKFLOW_REF?.match(/\.github\/workflows\/([^@]+)@/)?.[1];
const stop = self ? (await code.rest("GET", `/repos/${repository}/actions/workflows/${self}`)).state !== "active" : false;
// 止める時刻は後始末（bin/after.js）がリポジトリの変数に置く。
const variable = await code.rest("GET", `/repos/${repository}/actions/variables/${pauseVariable}`).catch(() => null);
const pause = variable && Date.parse(variable.value) > Date.now() ? variable.value : null;
// 担当のワークフローの実行。動いている担当は終わっていないもの（待っているものを含む）、落ちた実行は前の周の後に失敗で終わったもの。
const all = await code.rest("GET", `/repos/${repository}/actions/workflows/${workflow}/runs?per_page=100`);
const of = (r) => ({ number: runIssue(r.display_title), kind: r.display_title.replace(/^#\d+ /, ""), url: r.html_url, startedAt: r.run_started_at ?? r.created_at });
const ours = all.workflow_runs.filter((r) => runIssue(r.display_title));
const runs = ours.filter((r) => r.status !== "completed").map(of).sort((a, b) => a.number - b.number);
const failed = ours.filter((r) => r.conclusion === "failure" && Date.parse(r.updated_at) > since).map(of);
const running = new Set(runs.map((r) => r.number));
const board = await readBoard(bot, config);
const queue = queueOf(config, board);

const chosen = stop || pause ? [] : pick(config, queue, runs);
if (stop) say("見回りのワークフローが無効なので、振り出さずに見回りを終える");
else if (pause) say(`${pause} まで振り出しを止めている（リポジトリの変数 ${pauseVariable}）`);
else if (!chosen.length) say(`振り出すものは無い（動いている担当 ${running.size}）`);
for (const t of chosen) {
  say(`#${t.number}（${t.status}）を${t.kind}担当として起こす`);
  if (!dry) await code.rest("POST", `/repos/${repository}/actions/workflows/${workflow}/dispatches`, { ref: base, inputs: { issue: String(t.number), kind: t.kind } });
}

const waiting = ready(config, queue, running).filter((t) => !chosen.some((c) => c.number === t.number));
const later = dated(config, queue, running).map((t) => t.startOn);
const status = summary(config, {
  watcher,
  runs,
  started: chosen,
  waiting,
  held: queue.filter((t) => !running.has(t.number)).length - chosen.length - waiting.length - later.length,
  dated: later,
  stuck: stuck(config, { tasks: board.tasks, timeoutMinutes, waiting, left: free(config, [...runs, ...chosen]), failed, stop, pause }),
  stop,
  pause,
});
if (dry) say(`状況の更新（${status.status}）:\n${status.body}`);
else {
  const wrote = await putStatus(bot, config, status);
  if (wrote) say(`状況の更新を${wrote === "created" ? "足した" : "書き換えた"}（${status.status}）`);
}
if (stop) process.exit(3);
