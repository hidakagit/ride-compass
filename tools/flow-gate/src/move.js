// Claude の道具がステータスを動かす。ほかの経路と同じ照らし（rules.js: judge）で見て、通れば書く。
import { readTask, setField } from "./github.js";
import { judge } from "./rules.js";

// comment を渡すと、そのコメントを書いてから動かす。進行中へ入る（引き受ける）ときは、ほぼ同時に何者が来ても1者だけが通る:
// 引き受けの印（読んだ Status の値の更新時刻）を付けたコメントを先に書いてから読み直し、同じ回に先の印があれば、自分の
// コメントを消して断る。Project の欄の書き込みには、前の値を条件にする口が無いため。
export async function moveTask(gh, config, number, to, { comment, dryRun = false } = {}) {
  const { project, issue } = await readTask(gh, config, { number });
  if (!issue?.item || issue.state !== "OPEN") throw new Error(`#${number} は ${config.repository} の Project の開いた件ではありません。`);
  const verdict = judge(config, issue.status, to, { close: to === config.done ? "COMPLETED" : undefined, body: issue.body });
  if (!verdict.ok) throw new Error(verdict.reason);
  if (dryRun) return `（試し）#${number}: ${issue.status} → ${to}`;
  const status = setField(project, issue.item, config.project.statusField, to);
  if (to !== config.working) {
    await gh.write([...(comment ? [["addComment", { subjectId: issue.id, body: comment }]] : []), status]);
    return `#${number}: ${issue.status} → ${to}`;
  }
  const mark = `<!-- 引き受け ${issue.statusAt} -->`;
  const path = `/repos/${config.repository}/issues/${number}/comments`;
  const mine = await gh.rest("POST", path, { body: `${comment ?? `${to}にする`}\n\n${mark}` });
  const first = (await gh.rest("GET", `${path}?since=${encodeURIComponent(issue.statusAt)}&per_page=100`)).filter((c) => c.body?.endsWith(mark)).reduce((a, c) => (c.id < a.id ? c : a), mine);
  if (first.id !== mine.id) {
    await gh.rest("DELETE", `/repos/${config.repository}/issues/comments/${mine.id}`);
    throw new Error(`同じ「${issue.status}」を先に引き受けた書き手がいます（${first.html_url}）。`);
  }
  await gh.write([status]);
  return `#${number}: ${issue.status} → ${to}`;
}
