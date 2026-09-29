// ゲートを公開したあと、開いている issue の本文の先頭（ボタンとステータスの行）を、公開したゲートと同じ形に書き直す
// （hidakagit-bot の名義）。ゲートは出来事が来たときにしか本文を書き直さないので、ボタンの形を変えて公開すると、次の出来事まで古い
// ボタンが残る。書き直した出来事はゲートにも届くが、ゲートが出す形と同じなのでゲートは書き足さない。
// 使い方: node tools/flow-gate/bin/refresh.js
import { readFileSync } from "node:fs";
import config from "../flow.config.json" with { type: "json" };
import { GitHub, Mutations, readTask } from "../src/github.js";
import { normalizeBody, turnBody } from "../src/rules.js";
import { botToken } from "./token.js";

if (process.argv.length > 2) {
  console.error("使い方: node tools/flow-gate/bin/refresh.js");
  process.exit(2);
}
// ボタンの行き先と画像は、公開した Worker の変数（wrangler.toml の [vars]）と同じものを使う。
const toml = readFileSync(new URL("../wrangler.toml", import.meta.url), "utf8");
const origin = (name) => new RegExp(`^${name} = "([^"]+)"$`, "m").exec(toml)[1];
const links = { form: origin("FORM_ORIGIN"), image: `${origin("GATE_ORIGIN")}/button.svg` };

const gh = new GitHub(botToken());
const numbers = [];
for (let page = 1; ; page++) {
  const got = await gh.rest("GET", `/repos/${config.repository}/issues?state=open&per_page=100&page=${page}`);
  numbers.push(...got.filter((i) => !i.pull_request).map((i) => i.number));
  if (got.length < 100) break;
}
let changed = 0;
for (const number of numbers) {
  const { issue } = await readTask(gh, config, { number });
  if (!issue?.item) continue;
  const body = turnBody(config, links, issue);
  if (body === normalizeBody(issue.body)) continue;
  await new Mutations().add("updateIssue", { id: issue.id, body }).send(gh);
  console.log(`#${number}: 本文の先頭を書き直した（${issue.status}）`);
  changed++;
}
console.log(`開いている ${numbers.length} 件のうち ${changed} 件を書き直した`);
