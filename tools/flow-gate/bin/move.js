// Claude がタスクのステータスを名前で動かす（hidakagit-bot の名義）。表で照らすのはゲートで、ここは先に同じ表で断るだけ。
// 採否待ち・回答待ちへは動かさない（問いと一緒に ask.js で動かす）。
// 使い方: node tools/flow-gate/bin/move.js <issue の番号> <ステータス>
import config from "../flow.config.json" with { type: "json" };
import { GitHub, Mutations, readTask, setField } from "../src/github.js";
import { check } from "../src/rules.js";
import { botToken } from "./token.js";

const [number, to] = process.argv.slice(2);
if (!/^\d+$/.test(number ?? "") || !config.statuses.includes(to)) {
  console.error(`使い方: node tools/flow-gate/bin/move.js <issue の番号> <${config.statuses.join("|")}>`);
  process.exit(2);
}
if (config.ask.statuses.includes(to)) throw new Error(`「${to}」へは、問いと一緒に ask.js で動かします（docs/conventions/flow.md「問い」）。`);
const gh = new GitHub(botToken());
const { project, issue } = await readTask(gh, config, { number: Number(number) });
if (!issue?.item) throw new Error(`#${number} は ${config.repository} の Project の件ではありません。`);
const verdict = check(config, issue.status, to, issue.blockedBy.nodes);
if (!verdict.ok) throw new Error(verdict.reason);
await setField(new Mutations(), project, issue.item, config.project.statusField, to).send(gh);
console.log(`#${number}: ${issue.status} → ${to}`);
