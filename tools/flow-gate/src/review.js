// 検証中のタスクを、コードのリポジトリの Pull Request と master の CI の状態に合わせて動かす。Pull Request が閉じた・
// master の CI が終わった出来事から呼ぶ。今の状態を読み直してから決めるので、同じ出来事が2回届いても同じところへ落ち着く。
// 競合は出来事で届かないので扱わない（確かめる人が理由を書いて Pull Request を閉じ、閉じた出来事で戻る）。
// Pull Request は作業ブランチ（code.branchPrefix + issue の番号）で引く。コードのリポジトリは読むだけで、env.CODE_TOKEN で読む。
import { Gate } from "./gate.js";
import { GitHub } from "./github.js";
import { splitBody } from "./rules.js";

const PASSED = ["success", "skipped", "neutral"];

// Pull Request と CI から、検証中のタスクがどこへ動くべきかを決める。none は Pull Request がまだ無い（出されるのを待つ）。
export async function verdictFor(code, config, number) {
  const { repository, branchPrefix, base } = config.code;
  const owner = repository.split("/")[0];
  const [pr] = await code.rest("GET", `/repos/${repository}/pulls?head=${owner}:${branchPrefix}${number}&state=all&sort=created&direction=desc&per_page=1`);
  if (!pr) return { kind: "none" };
  if (pr.state === "open") return { kind: "wait", pr };
  if (!pr.merged_at) return { kind: "rejected", pr };
  const { workflow_runs: runs } = await code.rest("GET", `/repos/${repository}/actions/runs?head_sha=${pr.merge_commit_sha}&event=push&branch=${base}`);
  const failed = runs.filter((r) => r.status === "completed" && !PASSED.includes(r.conclusion));
  if (failed.length) return { kind: "failed", pr, runs: failed };
  return { kind: runs.length && runs.every((r) => r.status === "completed") ? "passed" : "wait", pr, runs };
}

// 検証中の候補を、Project の件の Status で引く（items の query はボードの絞り込みと同じ書き方）。1件ずつ読み直すときに Status で確かめる。
async function verifying(gate) {
  const { project, repository, verify } = gate.config;
  const d = await gate.gh.gql(
    `query Verifying($o: String!, $n: Int!, $q: String!) { organization(login: $o) { projectV2(number: $n) {
      items(first: 100, query: $q) { nodes { content { ... on Issue { number } } } } } } }`,
    { o: project.owner, n: project.number, q: `${project.statusField}:"${verify.status}" is:open repo:${repository}` },
  );
  return d.organization.projectV2.items.nodes.map((i) => i.content.number);
}

// リンクは Markdown の形で書く（URL をそのまま書くと、GitHub は直後の全角の文字まで URL に含めて開けないリンクにする）。
const link = (text, url) => `[${text.replace(/[[\]]/g, "\\$&")}](${url})`;
const prLink = (pr) => link(`#${pr.number} ${pr.title}`, pr.html_url);
const merged = (v) => `Pull Request ${prLink(v.pr)} をマージし、そのあとの master の CI が通りました（${v.runs.map((r) => link(r.name, r.html_url)).join("・")}）。`;
const MESSAGES = {
  rejected: (v) => `Pull Request ${prLink(v.pr)} がマージされずに閉じられました。コメントを読んでやり直してください。`,
  failed: (v) => `Pull Request ${prLink(v.pr)} のマージのあとの master の CI が通りませんでした。直してください。\n\n${v.runs.map((r) => `- ${link(r.name, r.html_url)}`).join("\n")}`,
  passed: (v) => `${merged(v)}完了にします。`,
  left: (v, left) =>
    `${merged(v)}完了の条件にチェックの無いものが残っているので、閉じずに戻します。残りを済ませてチェックを付け、完了（completed）で閉じてください。\n\n${left.map((l) => `- ${l}`).join("\n")}`,
};

// 本文のチェックの無い項目（`- [ ]`。本文のチェックは完了の条件にだけ使う）。
const unchecked = (body) =>
  splitBody(body)
    .rest.split("\n")
    .map((l) => /^\s*- \[ \] (.+)$/.exec(l)?.[1])
    .filter(Boolean);

// numbers を渡さなければ、検証中のタスクをすべて見る。
export async function reconcile(env, config, origin, numbers) {
  const gate = await Gate.open(env, config, origin);
  const code = new GitHub(env.CODE_TOKEN);
  const done = [];
  for (const number of numbers ?? (await verifying(gate))) {
    const issue = await gate.read({ number });
    if (!issue?.item || issue.status !== config.verify.status) continue;
    const v = await verdictFor(code, config, number);
    if (v.kind === "none" || v.kind === "wait") continue;
    const left = v.kind === "passed" ? unchecked(issue.body) : [];
    if (v.kind === "passed" && !left.length) await gate.apply(issue, issue.status, config.done, { comments: [MESSAGES.passed(v)], close: "COMPLETED" });
    else await gate.apply(issue, issue.status, config.verify.back, { comments: [left.length ? MESSAGES.left(v, left) : MESSAGES[v.kind](v)] });
    done.push(`#${number} ${left.length ? "left" : v.kind}`);
  }
  return done.join("・") || "動かすものは無い";
}
