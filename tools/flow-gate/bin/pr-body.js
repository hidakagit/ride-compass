// Pull Request の本文が .github/pull_request_template.md の形に沿うかを照らし、沿わなければ誤りを出して落ちる（src/pullrequest.js）。
// 担当が Pull Request を出す前と、claude-gate.yml の flow-gate が Pull Request の本文に打つ。GitHub に触れないので、master の版で
// 打ち直さず（bin/cli.js を読まない）、この作業ツリーのテンプレートで照らす。
import { readFileSync } from "node:fs";
import { checkBody } from "../src/pullrequest.js";

const [file] = process.argv.slice(2);
if (!file) {
  console.error("使い方: node tools/flow-gate/bin/pr-body.js <本文のファイル>");
  process.exit(2);
}
const template = readFileSync(new URL("../../../.github/pull_request_template.md", import.meta.url), "utf8");
const problems = checkBody(template, readFileSync(file, "utf8"));
for (const p of problems) console.error(p);
if (problems.length) {
  console.error("本文は .github/pull_request_template.md を写して節を埋める（.claude/skills/task-work/SKILL.md「作る担当」の5）");
  process.exit(1);
}
console.log("本文の形は .github/pull_request_template.md に沿っている");
