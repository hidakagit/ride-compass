// Claude の道具がステータスを動かす。行き先を、ほかの経路と同じ照らし（rules.js: judge）で見て、通れば書く。
import { Mutations, readTask, setField } from "./github.js";
import { judge } from "./rules.js";

// comment を渡すと、そのコメントを書いてから動かす。dryRun なら照らすだけで書かない。返すのは結果の1行。
export async function moveTask(gh, config, number, to, { comment, dryRun = false } = {}) {
  const { project, issue } = await readTask(gh, config, { number });
  if (!issue?.item || issue.state !== "OPEN") throw new Error(`#${number} は ${config.repository} の Project の開いた件ではありません。`);
  const verdict = judge(config, issue.status, to, { close: to === config.done ? "COMPLETED" : undefined, issue });
  if (!verdict.ok) throw new Error(verdict.reason);
  if (dryRun) return `（試し）#${number}: ${issue.status} → ${to}`;
  const m = new Mutations();
  if (to !== config.working) {
    if (comment) m.add("addComment", { subjectId: issue.id, body: comment });
    await setField(m, project, issue.item, config.project.statusField, to).send(gh);
    return `#${number}: ${issue.status} → ${to}`;
  }
  const mine = await claim(gh, config, issue, comment ?? `${to}にする`);
  try {
    await setField(m, project, issue.item, config.project.statusField, to).send(gh);
  } catch (e) {
    await gh.rest("DELETE", `/repos/${config.repository}/issues/comments/${mine.id}`).catch(() => {});
    throw e;
  }
  return `#${number}: ${issue.status} → ${to}`;
}

// 進行中へ入るのは、別々に動く書き手（振り出された作る担当・対話のセッション）がほぼ同時に通しうる。Project の欄の書き込みには
// 前の値を条件にする口が無いので、引き受けの印を付けたコメントを先に書いてから読み直し、同じ回（読んだ Status の値の更新時刻）の
// より古い印があれば、自分のコメントを消して引き下がる。印の付いたコメントは引き受けた側のものだけが残る。
async function claim(gh, config, issue, body) {
  const round = issue.statusAt;
  const mark = `<!-- 引き受け ${round} -->`;
  const comments = `/repos/${config.repository}/issues/${issue.number}/comments`;
  const mine = await gh.rest("POST", comments, { body: `${body}\n\n${mark}` });
  const listed = await gh.rest("GET", `${comments}?since=${encodeURIComponent(round)}&per_page=100`);
  const first = listed.filter((c) => c.body?.endsWith(mark)).reduce((a, c) => (c.id < a.id ? c : a), mine);
  if (first.id === mine.id) return mine;
  await gh.rest("DELETE", `/repos/${config.repository}/issues/comments/${mine.id}`);
  throw new Error(`同じ「${issue.status}」を先に引き受けた書き手がいます（${first.html_url}）。`);
}
