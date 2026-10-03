// Claude がステータスを動かす。行き先を、ほかの経路と同じ照らし（src/rules.js: judge）で見て、通れば書く。理由を渡すと、理由を
// コメントに書いてから動かす。書いた（dry なら試した）1行を返し、照らしが断れば理由を例外で投げる。
import { Mutations, readTask, setField } from "./github.js";
import { judge } from "./rules.js";

export async function moveTask(gh, config, number, to, reason, { dry = false } = {}) {
  const { project, issue } = await readTask(gh, config, { number });
  if (!issue?.item || issue.state !== "OPEN") throw new Error(`#${number} は ${config.repository} の Project の開いた件ではありません。`);
  const verdict = judge(config, issue.status, to, { close: to === config.done ? "COMPLETED" : undefined, issue });
  if (!verdict.ok) throw new Error(verdict.reason);
  if (dry) return `（試し）#${number}: ${issue.status} → ${to}`;
  const m = new Mutations();
  if (reason) m.add("addComment", { subjectId: issue.id, body: `${to}にする理由: ${reason.trim()}` });
  await setField(m, project, issue.item, config.project.statusField, to).send(gh);
  return `#${number}: ${issue.status} → ${to}`;
}
