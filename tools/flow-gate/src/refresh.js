// 開いた issue を全部、今のゲートの規則が書くはずの姿（担当者はステータスの番・本文の先頭はゲートが組み立てたもの）へ揃える。
// ゲートは出来事が届いた issue しか書き直さないので、規則を変えて公開した直後に流す（ci.yml の deploy-gate）。揃える書き込みは
// ゲートの Gate.write そのもので、規則の写しを持たない。揃っている issue には何も書かない。
import { Gate } from "./gate.js";
import { normalizeBody, ownerOf } from "./rules.js";

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
    const body = gate.bodyFor(issue);
    const owner = ownerOf(config, issue);
    const assigned = !owner || (issue.assignees.nodes.length === 1 && issue.assignees.nodes[0].id === config.people[owner].node);
    const why = [...(body !== normalizeBody(issue.body) ? ["本文の先頭"] : []), ...(assigned ? [] : ["担当者"])];
    if (!why.length) continue;
    changed.push({ number, why });
    if (!dry) await gate.write(issue);
  }
  return changed;
}
