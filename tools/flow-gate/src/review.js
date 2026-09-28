// 検証中のタスクを、コードのリポジトリの Pull Request と master の CI の状態に合わせて動かす。Pull Request が閉じた・
// master の CI が終わった出来事から呼ぶ。今の状態を読み直してから決めるので、同じ出来事が2回届いても同じところへ落ち着く。
// 競合は出来事で届かないので扱わない（確かめる人が理由を書いて Pull Request を閉じ、閉じた出来事で戻る）。
// Pull Request は作業ブランチ（code.branchPrefix + issue の番号）で引く。コードのリポジトリは読むだけで、env.CODE_TOKEN で読む。
import { Gate } from "./gate.js";
import { GitHub } from "./github.js";

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

// 検証中の候補は、ステータスのラベル（ゲートが Project の Status に合わせて付ける）で引く。1件ずつ読み直すときに Status で確かめる。
async function verifying(gate) {
  const [o, n] = gate.config.repository.split("/");
  const label = `${gate.config.statusLabelPrefix}${gate.config.verify.status}`;
  const d = await gate.gh.gql(
    `query Verifying($o: String!, $n: String!, $l: String!) { repository(owner: $o, name: $n) { issues(first: 100, states: OPEN, labels: [$l]) { nodes { number } } } }`,
    { o, n, l: label },
  );
  return d.repository.issues.nodes.map((i) => i.number);
}

const MESSAGES = {
  rejected: (v) => `Pull Request ${v.pr.html_url} がマージされずに閉じられました。コメントを読んでやり直してください。`,
  failed: (v) => `マージのあとの master の CI が通りませんでした。直してください。\n\n${v.runs.map((r) => `- ${r.name}: ${r.html_url}`).join("\n")}`,
  passed: (v) => `マージのあとの master の CI が通りました（${v.pr.html_url}）。完了にします。`,
};

// numbers を渡さなければ、検証中のタスクをすべて見る。
export async function reconcile(env, config, origin, numbers) {
  const gate = await Gate.open(env, config, origin);
  const code = new GitHub(env.CODE_TOKEN);
  const done = [];
  for (const number of numbers ?? (await verifying(gate))) {
    const issue = await gate.read({ number });
    if (!issue?.item || issue.parent || issue.status !== config.verify.status) continue;
    const v = await verdictFor(code, config, number);
    if (v.kind === "none" || v.kind === "wait") continue;
    const comments = [MESSAGES[v.kind](v)];
    if (v.kind !== "passed") {
      await gate.apply(issue, issue.status, config.verify.back, { comments });
    } else {
      // 段階が残っていれば、ゲートが閉じたときと同じく最初の段階だけを閉じて次の段階へ進める。
      const stage = issue.subIssues.nodes.find((s) => s.state === "OPEN");
      if (stage) await gate.write(issue, { status: config.nextStage.to, assign: config.nextStage.assign, closeOthers: [stage.id], comments });
      else await gate.apply(issue, issue.status, config.done, { comments, close: "COMPLETED" });
    }
    done.push(`#${number} ${v.kind}`);
  }
  return done.join("・") || "動かすものは無い";
}
