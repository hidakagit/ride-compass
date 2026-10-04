// Claude の道具がステータスを動かす。ほかの経路と同じ照らし（rules.js: judge）で見て、通れば書く。
// 同じタスクを触るのが1者だけなのは、担当のワークフローのグループ（.github/workflows/claude-task.yml の concurrency）が守る。
import { readTask, setField } from "./github.js";
import { judge } from "./rules.js";

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
