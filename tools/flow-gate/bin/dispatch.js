// 振り出し。担当のワークフロー（coordinator.workflow）を、動いている数が coordinator.parallel になるまで、キューの上から起こす。
// 起きるのは、担当のワークフローが終わったとき・定期・手で（.github/workflows/claude-dispatch.yml）。何か所から同時に起きても、
// 担当のワークフローの最初の段（作るなら振り出しの遷移が通るか、確かめるなら検証中か）が二重の作業を止める。
// 止めの印（ラベル coordinator.stopLabel）が置き場の開いた issue にあれば、何も起こさない（スマホからでも付けられる）。
// 使い方: node tools/flow-gate/bin/dispatch.js [--dry-run]（--dry-run は何を起こすかを出すだけで、何も起こさない）
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import config from "../flow.config.json" with { type: "json" };
import { pick, runIssue } from "../src/dispatch.js";
import { GitHub } from "../src/github.js";
import { botToken, codeToken } from "./token.js";

const args = process.argv.slice(2);
if (args.some((a) => a !== "--dry-run")) {
  console.error("使い方: node tools/flow-gate/bin/dispatch.js [--dry-run]");
  process.exit(2);
}
const dry = args.includes("--dry-run");
const say = (line) => console.log(`${dry ? "（試し）" : ""}${line}`);
const here = dirname(fileURLToPath(import.meta.url));
const { stopLabel, workflow } = config.coordinator;
const { repository, base } = config.code;

const [o, n] = config.repository.split("/");
const stop = await new GitHub(botToken()).gql(
  `query Stop($o: String!, $n: String!, $l: [String!]) { repository(owner: $o, name: $n) { issues(states: OPEN, labels: $l, first: 1) { nodes { number } } } }`,
  { o, n, l: [stopLabel] },
);
if (stop.repository.issues.nodes[0]) {
  say(`#${stop.repository.issues.nodes[0].number} にラベル「${stopLabel}」が付いているので、振り出さない`);
  process.exit(0);
}

// 動いている担当: 担当のワークフローの実行のうち、終わっていないもの（待っているものを含む）。
const code = new GitHub(codeToken());
const runs = await code.rest("GET", `/repos/${repository}/actions/workflows/${workflow}/runs?per_page=100`);
const running = new Set(runs.workflow_runs.filter((r) => r.status !== "completed").map((r) => runIssue(r.display_title)).filter(Boolean));
const queue = JSON.parse(execFileSync(process.execPath, [join(here, "queue.js"), "--json"], { encoding: "utf8" }));
const chosen = pick(config, queue, running);
if (!chosen.length) say(`振り出すものは無い（動いている担当 ${running.size}）`);
for (const t of chosen) {
  say(`#${t.number}（${t.status}）を${t.kind}担当として起こす`);
  if (!dry) await code.rest("POST", `/repos/${repository}/actions/workflows/${workflow}/dispatches`, { ref: base, inputs: { issue: String(t.number), kind: t.kind } });
}
