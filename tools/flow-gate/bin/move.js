// Claude がタスクのステータスを名前で動かす（hidakagit-bot の名義）。表で照らすのはゲートで、ここは先に同じ表で断るだけ。
// 回答待ちへは動かさない（問いと一緒に ask.js で動かす）。保留へは理由が要り、理由をコメントに書いてから動かす
// （保留はユーザーの棚卸の対象で、棚卸では理由を読んで決める）。
// 使い方: node tools/flow-gate/bin/move.js <issue の番号> <ステータス>（保留なら続けて <理由>）
import config from "../flow.config.json" with { type: "json" };
import { GitHub, Mutations, readTask, setField } from "../src/github.js";
import { check } from "../src/rules.js";
import { botToken } from "./token.js";

const args = process.argv.slice(2);
const [number, to, reason] = args;
if (args.length !== (to === config.hold ? 3 : 2) || !/^\d+$/.test(number) || !config.statuses.includes(to) || (to === config.hold && !reason.trim())) {
  console.error(`使い方: node tools/flow-gate/bin/move.js <issue の番号> <${config.statuses.join("|")}>（${config.hold}なら続けて <理由>）`);
  process.exit(2);
}
if (to === config.ask.status) throw new Error(`「${to}」へは、問いと一緒に ask.js で動かします（docs/conventions/flow.md「問い」）。`);
const gh = new GitHub(botToken());
const { project, issue } = await readTask(gh, config, { number: Number(number) });
if (!issue?.item) throw new Error(`#${number} は ${config.repository} の Project の件ではありません。`);
const verdict = check(config, issue.status, to, issue.blockedBy.nodes);
if (!verdict.ok) throw new Error(verdict.reason);
const m = new Mutations();
if (to === config.hold) m.add("addComment", { subjectId: issue.id, body: `${config.hold}にする理由: ${reason.trim()}` });
await setField(m, project, issue.item, config.project.statusField, to).send(gh);
console.log(`#${number}: ${issue.status} → ${to}`);
