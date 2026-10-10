// Claude の道具がステータスを動かす。ほかの経路と同じ照らし（rules.js: judge）で見て、通れば書く。
// 同じタスクを触るのが1者だけなのは、担当のワークフローのグループ（.github/workflows/claude-task.yml の concurrency）が守る。
import { readTask, setField } from "./github.js";
import { checkQuestion, isExchange, judge, normalize, SCAN } from "./rules.js";

const read = (gh, config, number) => readTask(gh, config, { number }, { comments: SCAN });

// comment を渡すと、そのコメントを書いてから動かす（同じ要求で）。
export async function moveTask(gh, config, number, to, options) {
  return moveRead(gh, config, number, to, await read(gh, config, number), options);
}

async function moveRead(gh, config, number, to, { project, issue }, { comment, dryRun = false } = {}) {
  if (!issue?.item || issue.state !== "OPEN") throw new Error(`#${number} は ${config.repository} の Project の開いた件ではありません。`);
  const verdict = judge(config, issue.status, to, { close: to === config.done ? "COMPLETED" : undefined, body: issue.body, comments: [...issue.comments.nodes.map((c) => c.body), comment] });
  if (!verdict.ok) throw new Error(verdict.reason);
  if (dryRun) return `（試し）#${number}: ${issue.status} → ${to}`;
  await gh.write([...(comment ? [["addComment", { subjectId: issue.id, body: comment }]] : []), setField(project, issue.item, config.project.statusField, to)]);
  return `#${number}: ${issue.status} → ${to}`;
}

// Claude がユーザーに問う。形に合わなければ断り、問いをコメントに書いて回答待ちへ動かす。もう回答待ちなら動かさずにコメントだけを書く（問い直し）。
// 答えの無い最新の問いが同じ文なら書き直さない——書く要求は失敗の応答でも通っていることがあり（github.js: again）、
// 落ちた打ちを打ち直すと問いが2つになる。
export async function askTask(gh, config, number, question) {
  const problems = checkQuestion(config.questionTemplate, question);
  if (problems.length) throw new Error(`問いが形（tools/flow-gate/question_template.md）に合いません: ${problems.join("・")}`);
  const task = await read(gh, config, number);
  const { issue } = task;
  const last = issue?.comments.nodes.findLast((c) => isExchange(c.body));
  const comment = last && normalize(last.body).trim() === question ? undefined : question;
  if (issue?.state !== "OPEN" || issue.status !== config.waiting) return moveRead(gh, config, number, config.waiting, task, { comment });
  if (comment) await gh.write([["addComment", { subjectId: issue.id, body: comment }]]);
  return `#${number}: 回答待ちのまま${comment ? "問い直した" : "（同じ問いがあるので書かなかった）"}`;
}
