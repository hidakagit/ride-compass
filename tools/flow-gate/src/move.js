// Claude の道具がステータスを動かす。ほかの経路と同じ照らし（rules.js: judge）で見て、通れば書く。
// 同じタスクを触るのが1者だけなのは、担当のワークフローのグループ（.github/workflows/claude-task.yml の concurrency）が守る。
import { readTask, setField } from "./github.js";
import { judge, normalize, SCAN } from "./rules.js";

// comment を渡すと、そのコメントを書いてから動かす（同じ要求で）。
export async function moveTask(gh, config, number, to, { comment, dryRun = false } = {}) {
  const { project, issue } = await readTask(gh, config, { number });
  if (!issue?.item || issue.state !== "OPEN") throw new Error(`#${number} は ${config.repository} の Project の開いた件ではありません。`);
  const verdict = judge(config, issue.status, to, { close: to === config.done ? "COMPLETED" : undefined, body: issue.body });
  if (!verdict.ok) throw new Error(verdict.reason);
  if (dryRun) return `（試し）#${number}: ${issue.status} → ${to}`;
  await gh.write([...(comment ? [["addComment", { subjectId: issue.id, body: comment }]] : []), setField(project, issue.item, config.project.statusField, to)]);
  return `#${number}: ${issue.status} → ${to}`;
}

// Claude がユーザーに問う。問いをコメントに書いて回答待ちへ動かす。もう回答待ちなら動かさずにコメントだけを書く（問い直し）。
// 答えの無い最新の問いが同じ文なら書き直さない——書く要求は失敗の応答でも通っていることがあり（github.js: again）、
// 落ちた打ちを打ち直すと問いが2つになる。
export async function askTask(gh, config, number, question) {
  const { issue } = await readTask(gh, config, { number }, { comments: SCAN });
  const last = issue?.comments.nodes.findLast((c) => /^## (問い|回答)\n/.test(normalize(c.body)));
  const comment = last && normalize(last.body).trim() === question ? undefined : question;
  if (issue?.state !== "OPEN" || issue.status !== config.waiting) return moveTask(gh, config, number, config.waiting, { comment });
  if (comment) await gh.write([["addComment", { subjectId: issue.id, body: comment }]]);
  return `#${number}: 回答待ちのまま${comment ? "問い直した" : "（同じ問いがあるので書かなかった）"}`;
}
