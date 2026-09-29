// Claude が hidakagit に問う（hidakagit-bot の名義）。問いを本文の先頭（ゲートの印の間）に画面に出ない形で書き、回答待ちへ動かす
// （もう回答待ちなら hidakagit に割り当て直す）。ボタンはゲートが出す。
// 使い方: node tools/flow-gate/bin/ask.js <issue の番号> <問いのファイル（docs/conventions/flow.md「問い」の形）>
import { readFileSync } from "node:fs";
import config from "../flow.config.json" with { type: "json" };
import { GitHub, Mutations, readTask, setField } from "../src/github.js";
import { check, joinBody, normalizeBody, parseQuestion, splitBody } from "../src/rules.js";
import { botToken } from "./token.js";

const args = process.argv.slice(2);
const [number, file] = args;
if (args.length !== 2 || !/^\d+$/.test(number)) {
  console.error("使い方: node tools/flow-gate/bin/ask.js <issue の番号> <問いのファイル>");
  process.exit(2);
}
const question = normalizeBody(readFileSync(file, "utf8")).trim();
if (question.includes("-->")) throw new Error("問いに「-->」を含められません（本文の中で問いを隠す HTML のコメントが途中で閉じるため）。");
if (!parseQuestion(config, question)) throw new Error("問いが形（docs/conventions/flow.md「問い」）に合いません。");

const gh = new GitHub(botToken());
const { project, issue } = await readTask(gh, config, { number: Number(number) });
if (!issue?.item || issue.state !== "OPEN") throw new Error(`#${number} は ${config.repository} の Project の開いた件ではありません。`);
const to = config.ask.status;
const asking = issue.status === to;
if (!asking) {
  const verdict = check(config, issue.status, to, issue.blockedBy.nodes);
  if (!verdict.ok) throw new Error(verdict.reason);
}

// 本文を先に書く（ステータスが動いた出来事を受けたゲートが、本文の問いを読んで照らすため）。
const m = new Mutations();
const update = { id: issue.id, body: joinBody(splitBody(issue.body).rest, question, null) };
if (asking) update.assigneeIds = [config.people[config.ask.answerer].node];
m.add("updateIssue", update);
if (!asking) setField(m, project, issue.item, config.project.statusField, to);
await m.send(gh);
console.log(asking ? `#${number}: ${issue.status} のまま問いを書き、${config.ask.answerer} に割り当てた` : `#${number}: 問いを書き、${issue.status} → ${to}`);
