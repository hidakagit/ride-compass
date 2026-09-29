// 本文の先頭の問いのうち、今の形の規則（src/rules.js: parseQuestion）で読めないものを、今の形（「### 案」）へ一度で直す
// （hidakagit-bot の名義）。直す対象は今の規則から導き、別の見分け方を持たない。ゲートは今の形だけを読むので、公開の直後に
// 流す（ci.yml の deploy-gate）。今の規則で読めない問いが無ければ何もしない。
// 直し方は、前の形（「### 選択肢」の各行に「 → 行き先 / 次に動く者」）を受け付けていたゲートの規則そのもの（行を最初の「 → 」（前後に空白）で分け、前が文、後ろが「 / 」
// 区切りのステータス名か人の名前）で読むので、前の回答フォームに出ていた文がそのまま案になる。行き先が回答フォームの一律の
// 選択肢（止める・完成・見送り）で選べる選択肢は落とす。直した結果も今の規則で読めることを確かめてから書き、前の規則でも
// 読めない・直しても読めない問いは直さずに名を出す。
// 使い方: node tools/flow-gate/bin/migrate-questions.js [--dry-run]（--dry-run は直した後の案を出すだけで、書かない）
import config from "../flow.config.json" with { type: "json" };
import { GitHub, Mutations } from "../src/github.js";
import { joinBody, parseQuestion, splitBody } from "../src/rules.js";
import { botToken } from "./token.js";

const dry = process.argv.includes("--dry-run");
const go = config.answers.find((a) => a.plans).to;
const covered = config.answers.map((a) => a.to).filter((s) => s !== go);
const people = Object.keys(config.people);

// 前のゲートの読み方で選択肢を読む。読めなければ null。
function oldOptions(question) {
  const lines = question.split("\n");
  const at = lines.findIndex((l) => l.trim() === "### 選択肢");
  if (at < 0) return null;
  const options = [];
  let end = lines.length;
  for (let k = at + 1; k < lines.length; k++) {
    const line = lines[k];
    if (!line.trim()) {
      if (options.length) {
        end = k;
        break;
      }
      continue;
    }
    if (!line.startsWith("- ")) {
      end = k;
      break;
    }
    const [label, rest] = line.slice(2).split(" → ");
    const option = { text: label.trim(), to: null };
    for (const part of rest ? rest.split(" / ").map((p) => p.trim()) : []) {
      if (config.statuses.includes(part)) option.to = part;
      else if (!people.includes(part) && part !== "Claude") return null;
    }
    if (!option.text) return null;
    options.push(option);
  }
  return options.length < 2 ? null : { at, end, options };
}

const gh = new GitHub(botToken());
const [o, n] = config.repository.split("/");
const m = new Mutations();
let after = null;
do {
  const d = await gh.gql(
    `query Open($o: String!, $n: String!, $c: String) { repository(owner: $o, name: $n) { issues(states: OPEN, first: 100, after: $c) {
      pageInfo { hasNextPage endCursor } nodes { id number body } } } }`,
    { o, n, c: after },
  );
  const page = d.repository.issues;
  for (const issue of page.nodes) {
    const { question, rest } = splitBody(issue.body);
    if (!question || parseQuestion(question)) continue;
    const old = oldOptions(question);
    if (!old) {
      console.log(`#${issue.number}: 今の規則でも前の規則でも読めないので直さない`);
      continue;
    }
    const lines = question.split("\n");
    const plans = old.options.filter((x) => !covered.includes(x.to)).map((x) => `- ${x.text}`);
    const next = [...lines.slice(0, old.at), ...(plans.length ? ["### 案", ...plans] : []), ...lines.slice(old.end)].join("\n").replace(/\n{3,}/g, "\n\n");
    if (!parseQuestion(next)) {
      console.log(`#${issue.number}: 直しても今の規則で読めないので直さない`);
      continue;
    }
    console.log(`#${issue.number}: 今の規則で読めない問いを直す（案 ${plans.length} 件）`);
    if (dry) console.log(`案: ${JSON.stringify(plans.map((x) => x.slice(2)))}`);
    else m.add("updateIssue", { id: issue.id, body: joinBody(rest, next, null) });
  }
  after = page.pageInfo.hasNextPage ? page.pageInfo.endCursor : null;
} while (after);
if (!dry) await m.send(gh);
