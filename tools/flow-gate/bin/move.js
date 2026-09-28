// Claude がタスクのステータスを名前で動かす（hidakagit-bot の名義）。表で照らすのはゲートで、ここは先に同じ表で断るだけ。
// 使い方: node tools/flow-gate/bin/move.js <issue の番号> <ステータス>
import { execFileSync } from "node:child_process";
import config from "../flow.config.json" with { type: "json" };
import { currentQuestion } from "../src/gate.js";
import { GitHub, readIssue, readProject } from "../src/github.js";
import { check } from "../src/rules.js";

// Windows のユーザー環境変数は、それより前に起動したプロセスの環境には入らないので、無ければ登録簿から読む。
function token() {
  if (process.env.FLOW_BOT_TOKEN) return process.env.FLOW_BOT_TOKEN;
  const out = execFileSync("reg", ["query", "HKCU\\Environment", "/v", "FLOW_BOT_TOKEN"], { encoding: "utf8" });
  return /FLOW_BOT_TOKEN\s+REG_SZ\s+(\S+)/.exec(out)[1];
}

const [number, to] = process.argv.slice(2);
if (!/^\d+$/.test(number ?? "") || !config.statuses.includes(to)) {
  console.error(`使い方: node tools/flow-gate/bin/move.js <issue の番号> <${config.statuses.join("|")}>`);
  process.exit(2);
}
const gh = new GitHub(token());
const project = await readProject(gh, config);
const issue = await readIssue(gh, config, project, { number: Number(number) });
if (!issue?.item) throw new Error(`#${number} は ${config.repository} の Project の件ではありません。`);
const verdict = check(config, issue.status, to, issue.blockedBy.nodes);
if (!verdict.ok) throw new Error(verdict.reason);
if (config.ask.statuses.includes(to) && to !== config.adoption.status && !currentQuestion(config, issue)?.parsed)
  throw new Error("今の問いが形（docs/conventions/flow.md「問い」）に合いません。問いを書いてから動かしてください。");
await gh.gql(
  `mutation Set($p: ID!, $i: ID!, $f: ID!, $o: String!) { updateProjectV2ItemFieldValue(input: { projectId: $p, itemId: $i, fieldId: $f, value: { singleSelectOptionId: $o } }) { clientMutationId } }`,
  { p: project.id, i: issue.item, f: project.field, o: project.options[to] },
);
console.log(`#${number}: ${issue.status} → ${to}`);
