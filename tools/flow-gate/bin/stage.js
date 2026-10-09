// Claude がタスクを段階に分ける。段階は親の子（GitHub の sub-issue）として、親と同じ種類で作る（Project へは「Auto-add sub-issues to project」が
// 入れ、ゲートが入口で未着手にする）。前の段階は段階の前提（blocked by）に、段階は親の前提に張り、親が進行中なら
// 未着手へ戻す（段階が全部閉じるまで、親は前提待ちで振り出されない）。
import { readFileSync } from "node:fs";
import { readTask } from "../src/github.js";
import { moveTask } from "../src/move.js";
import { notes } from "../src/rules.js";
import { args, bot, config, isNumber } from "./cli.js";

const { rest: [parent, title, file, ...before] } = args("node tools/flow-gate/bin/stage.js <親の番号> <題名> <本文のファイル> [前の段階の番号...]",
  (a) => a.length >= 3 && isNumber(a[0]) && a.slice(3).every(isNumber));
const gh = bot();
const [o, n] = config.repository.split("/");
const ids = await Promise.all([parent, ...before].map(async (k) => (await readTask(gh, config, { number: Number(k) })).issue.id));
const repo = (await gh.gql("query R($o: String!, $n: String!, $k: Int!) { repository(owner: $o, name: $n) { id issue(number: $k) { issueType { id } } } }",
  { o, n, k: Number(parent) })).repository;
const stage = (await gh.gql(`mutation C($i: CreateIssueInput!) { createIssue(input: $i) { issue { id number url } } }`,
  { i: { repositoryId: repo.id, parentIssueId: ids[0], issueTypeId: repo.issue.issueType?.id, title, body: readFileSync(file, "utf8") } })).createIssue.issue;
await gh.write([...ids.slice(1).map((b) => ["addBlockedBy", { issueId: stage.id, blockingIssueId: b }]), ["addBlockedBy", { issueId: ids[0], blockingIssueId: stage.id }]]);
console.log(`段階 #${stage.number} ${stage.url}`);
if ((await readTask(gh, config, { number: Number(parent) })).issue.status === config.working)
  console.log(await moveTask(gh, config, Number(parent), config.todo, { comment: notes.reason(config.todo, `段階 #${stage.number} に分けた。段階が全部閉じるまで、段階に blocked by されて待つ`) }));
