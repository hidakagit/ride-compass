// 開いた issue を全部、今のゲートの規則が書くはずの姿（担当者はステータスの番・本文の先頭はゲートが組み立てたもの）へ揃える。
// ゲートは出来事が届いた issue しか書き直さないので、規則を変えて公開した直後に流す（ci.yml の deploy-gate）。揃える書き込みは
// ゲートの Gate.write そのもので、規則の写しを持たない。揃っている issue には何も書かない。
import { Gate } from "./gate.js";
import { joinBody, normalizeBody, ownerOf, parseQuestion, splitBody } from "./rules.js";

// 開いた issue の番号（置き場の全ページ）。
async function openIssues(gh, config) {
  const [o, n] = config.repository.split("/");
  const numbers = [];
  for (let after = null; ; ) {
    const d = await gh.gql(
      `query Open($o: String!, $n: String!, $c: String) { repository(owner: $o, name: $n) { issues(states: OPEN, first: 100, after: $c) {
        pageInfo { hasNextPage endCursor } nodes { number } } } }`,
      { o, n, c: after },
    );
    const page = d.repository.issues;
    numbers.push(...page.nodes.map((i) => i.number));
    if (!page.pageInfo.hasNextPage) return numbers;
    after = page.pageInfo.endCursor;
  }
}

// 揃える。dry なら書かずに、揃える issue の番号と理由だけを返す。
export async function refreshAll(env, config, { dry = false } = {}) {
  const gate = await Gate.open(env, config);
  const changed = [];
  for (const number of await openIssues(gate.gh, config)) {
    const issue = await gate.read({ number });
    if (!issue?.item) continue;
    const want = {};
    const { question, rest } = splitBody(issue.body);
    const fixed = question && !parseQuestion(question) ? fromOldForm(config, question) : null;
    if (fixed) want.question = fixed;
    const body = gate.bodyFor({ ...issue, body: fixed ? joinBody(rest, fixed, null) : issue.body });
    const owner = ownerOf(config, issue);
    const assigned = !owner || (issue.assignees.nodes.length === 1 && issue.assignees.nodes[0].id === config.people[owner].node);
    const why = [...(fixed ? ["前の形の問い"] : []), ...(body !== normalizeBody(issue.body) ? ["本文の先頭"] : []), ...(assigned ? [] : ["担当者"])];
    if (!why.length) continue;
    changed.push({ number, why });
    if (!dry) await gate.write(issue, want);
  }
  return changed;
}

// 前の形の問い（「### 選択肢」の各行に「 → 行き先 / 次に動く者」）を今の形（「### 案」）へ直す。読み方は前の形を受け付けていた
// ゲートの規則そのもの（行を最初の「 → 」（前後に空白）で分け、前が文、後ろが「 / 」区切りのステータス名か人の名前）なので、
// 前の回答フォームに出ていた文がそのまま案になる。回答フォームの一律の選択肢（止める・完成・見送り）で選べる行き先の選択肢は
// 落とす。前の規則でも読めない・直しても今の規則で読めないものは null（直さない）。前の形の問いが無くなったら消す。
function fromOldForm(config, question) {
  const lines = question.split("\n");
  const at = lines.findIndex((l) => l.trim() === "### 選択肢");
  if (at < 0) return null;
  const go = config.answers.find((a) => a.plans).to;
  const covered = config.answers.map((a) => a.to).filter((s) => s !== go);
  const names = [...Object.keys(config.people), "Claude"];
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
    const [label, tail] = line.slice(2).split(" → ");
    let to = null;
    for (const part of tail ? tail.split(" / ").map((p) => p.trim()) : []) {
      if (config.statuses.includes(part)) to = part;
      else if (!names.includes(part)) return null;
    }
    if (!label.trim()) return null;
    options.push({ text: label.trim(), to });
  }
  if (options.length < 2) return null;
  const plans = options.filter((x) => !covered.includes(x.to)).map((x) => `- ${x.text}`);
  const next = [...lines.slice(0, at), ...(plans.length ? ["### 案", ...plans] : []), ...lines.slice(end)].join("\n").replace(/\n{3,}/g, "\n\n");
  return parseQuestion(next) ? next : null;
}
