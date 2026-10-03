// Claude がタスクを段階に分ける（hidakagit-bot の名義）。段階は親を付けたまま作る（作ってから親を付けると、Project に入った
// 時点で段階と分からず、入口で採否の問いが付く）。Project へは「Auto-add sub-issues to project」が入れ、ゲートが入口で未着手にする。
// 親はその段階に blocked by され、進行中なら未着手へ戻る（段階が全部閉じると前提が閉じ、見回りが親を作る担当へ渡す）。
// 使い方: node tools/flow-gate/bin/stage.js <親の番号> <題名> <本文のファイル> [前の段階の番号...]（前の段階は blocked by になる）
import { readFileSync } from "node:fs";
import config from "../flow.config.json" with { type: "json" };
import { GitHub, Mutations, readTask } from "../src/github.js";
import { moveTask } from "../src/move.js";
import { botToken } from "./token.js";

const args = process.argv.slice(2);
const [parent, title, file, ...after] = args;
if (args.some((a) => a.startsWith("--")) || !/^\d+$/.test(parent ?? "") || !title || !file || after.some((n) => !/^\d+$/.test(n))) {
  console.error("使い方: node tools/flow-gate/bin/stage.js <親の番号> <題名> <本文のファイル> [前の段階の番号...]");
  process.exit(2);
}
const gh = new GitHub(botToken());
const [o, n] = config.repository.split("/");
const numbers = [Number(parent), ...after.map(Number)];
const d = await gh.gql(
  `query Ids($o: String!, $n: String!) { repository(owner: $o, name: $n) { id ${numbers.map((k, i) => `i${i}: issue(number: ${k}) { id state }`).join(" ")} } }`,
  { o, n },
);
const issues = numbers.map((_, i) => d.repository[`i${i}`]);
if (!issues[0] || issues[0].state !== "OPEN") throw new Error(`親 #${parent} は ${config.repository} の開いた issue ではありません。`);
if (issues.some((i) => !i)) throw new Error("前の段階に、置き場に無い番号があります。");

const created = await new Mutations()
  .add("createIssue", { repositoryId: d.repository.id, parentIssueId: issues[0].id, title, body: readFileSync(file, "utf8") }, "issue { id number url }")
  .send(gh);
const stage = created.m0.issue;
const m = new Mutations();
for (const blocking of issues.slice(1)) m.add("addBlockedBy", { issueId: stage.id, blockingIssueId: blocking.id });
m.add("addBlockedBy", { issueId: issues[0].id, blockingIssueId: stage.id });
await m.send(gh);
const { issue: owner } = await readTask(gh, config, { number: Number(parent) });
if (owner?.status === config.working) console.log(await moveTask(gh, config, Number(parent), config.todo, `段階 #${stage.number} に分けた。段階が全部閉じるまで、段階に blocked by されて待つ`));
console.log(`#${stage.number} ${stage.url}（親 #${parent}${after.length ? `・前の段階 ${after.map((k) => `#${k}`).join("・")}` : ""}）`);
