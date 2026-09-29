// 本文の先頭に残る古い形の問い（「### 選択肢」の各行に「→ 行き先 / 次に動く者」を書いた形）を、今の形（「### 案」）へ
// 書き換える（hidakagit-bot の名義）。行き先が保留・完了の選択肢は、回答フォームが一律に出す「止める」「見送り」で選べる
// ので落とし、残りを案にする。ゲートの公開（ci.yml の deploy-gate）のあとに流す。古い形が無ければ何もしない。
// 使い方: node tools/flow-gate/bin/migrate-questions.js [--dry-run]（--dry-run は書き換えた後の問いを出すだけで、書かない）
import config from "../flow.config.json" with { type: "json" };
import { GitHub, Mutations } from "../src/github.js";
import { joinBody, splitBody } from "../src/rules.js";
import { botToken } from "./token.js";

const gh = new GitHub(botToken());
const [o, n] = config.repository.split("/");
const d = await gh.gql(
  `query Open($o: String!, $n: String!) { repository(owner: $o, name: $n) { issues(states: OPEN, first: 100) { nodes { id number body } } } }`,
  { o, n },
);
// 回答フォームが「進める」以外の選択肢で一律に出す行き先（止める・完成・見送り）。
const go = config.answers.find((a) => a.plans).to;
const dropped = config.answers.map((a) => a.to).filter((s) => s !== go);
const m = new Mutations();
for (const issue of d.repository.issues.nodes) {
  const { question, rest } = splitBody(issue.body);
  if (!question?.includes("\n### 選択肢\n")) continue;
  const [head, tail] = question.split("\n### 選択肢\n");
  const lines = tail.split("\n");
  const end = lines.findIndex((l, i) => i > 0 && !l.startsWith("- ") && l.trim());
  const options = (end < 0 ? lines : lines.slice(0, end)).filter((l) => l.startsWith("- "));
  const plans = options.filter((l) => !dropped.includes(l.split(" → ")[1]?.split(" / ")[0]?.trim())).map((l) => `- ${l.slice(2).split(" → ")[0].trim()}`);
  const after = end < 0 ? "" : lines.slice(end).join("\n");
  const next = [head.trimEnd(), ...(plans.length ? ["", "### 案", ...plans] : []), ...(after ? ["", after] : [])].join("\n");
  m.add("updateIssue", { id: issue.id, body: joinBody(rest, next, null) });
  console.log(`#${issue.number}: 古い形の問いを書き換えた（案 ${plans.length} 件）`);
  if (process.argv.includes("--dry-run")) console.log(next.split("<details>")[0]);
}
if (!process.argv.includes("--dry-run")) await m.send(gh);
