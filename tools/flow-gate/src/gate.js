// ゲート: GitHub の出来事と回答フォームの送信を受け、遷移の表で照らして書く。1つの出来事では、タスクを1回読み、1回で書く。
import { GitHub, readTask, setField } from "./github.js";
import { bodyRest, judge, normalize, notes, ownerOf, SCAN, unanswered, withButton } from "./rules.js";

export class Gate {
  // App の名義で読み書きする。
  static async open(env, config) {
    const gate = new Gate();
    gate.config = config;
    gate.gh = await GitHub.asApp(env, config.installation);
    return gate;
  }

  // 答えていない問いを見分けるため、コメントは回答フォームが今の問いを探すのと同じ件数を読む。
  async read(ref, options) {
    const r = await readTask(this.gh, this.config, ref, { comments: SCAN, ...options });
    this.project = r.project;
    this.labelIds = r.labels;
    return r.issue;
  }

  // 本文: 回答待ちの間だけ、先頭に回答フォームへのボタン（画像は GitHub が中継して取りに来るので Access の外の urls.gate から返す）。
  bodyFor(issue) {
    const rest = bodyRest(issue.body);
    const { gate, form } = this.config.urls;
    return issue.state === "OPEN" && issue.status === this.config.waiting ? withButton(rest, `${form}/answer?issue=${issue.number}`, `${gate}/button.svg`) : rest;
  }

  // 問い: 回答待ちの間、答えていない問いが無ければ（どの経路で入ったかによらず）、回答フォームで答えられるように問いを1つ置く。
  questionFor(issue, comments = []) {
    const bodies = [...issue.comments.nodes.map((c) => c.body), ...comments];
    return issue.state === "OPEN" && issue.status === this.config.waiting && !unanswered(bodies) ? [`## 問い\n${this.config.question}`] : [];
  }

  // want に変えたいものだけを渡す（status・comments・labels・unlabels・close・reopen・body）。担当者はステータスの番、
  // 本文の先頭と問いは書いた後の状態に合わせて、同じ要求に入れる。
  async write(issue, want = {}) {
    const next = { ...issue, status: want.status ?? issue.status, state: want.close ? "CLOSED" : want.reopen ? "OPEN" : issue.state, body: want.body ?? issue.body };
    const ops = [];
    if (next.status !== issue.status) ops.push(setField(this.project, issue.item, this.config.project.statusField, next.status));
    for (const body of [...(want.comments ?? []), ...this.questionFor(next, want.comments)]) ops.push(["addComment", { subjectId: issue.id, body }]);
    if (want.reopen) ops.push(["reopenIssue", { issueId: issue.id }]);
    const update = {};
    const owner = ownerOf(this.config, next);
    if (owner && (issue.assignees.nodes.length !== 1 || issue.assignees.nodes[0].login !== owner)) update.assigneeIds = [this.config.people[owner].node];
    const have = issue.labels.nodes.map((l) => l.name);
    const labels = [...new Set([...have.filter((n) => !want.unlabels?.includes(n)), ...(want.labels ?? [])])].filter((n) => this.labelIds[n]);
    if (labels.length !== have.length || labels.some((n) => !have.includes(n))) update.labelIds = labels.map((n) => this.labelIds[n]);
    const body = this.bodyFor(next);
    if (body !== normalize(issue.body)) update.body = body;
    if (want.close) update.stateInput = { value: "CLOSED", stateReason: want.close };
    if (Object.keys(update).length) ops.push(["updateIssue", { id: issue.id, ...update }]);
    await this.gh.write(ops);
  }

  // 今のステータスから to へ動かす（回答フォーム・Pull Request）。照らしを通れば書く。完了へは close（無ければ見送り）で閉じる。
  // body は本文の書き換え（回答フォームで残りの条件にチェックを付けたとき）で、書き換えた本文で照らす。
  async apply(issue, to, { close, body, ...rest } = {}) {
    const closing = to === this.config.done ? (close ?? "NOT_PLANNED") : undefined;
    const verdict = judge(this.config, issue.status, to, { close: closing, body: body ?? issue.body });
    if (verdict.ok) await this.write(issue, { ...rest, status: to, body, close: issue.state === "OPEN" ? closing : undefined });
    return verdict;
  }

  // Project に入った: 段階（親のある issue）とユーザーの起票は未着手、Claude の起票は回答待ち（問いは write が置く）。
  // 欄（優先度等）は書かない（誰も決めていない欄は空のまま見せ、起票の直後に入れた値を、読んでから書くまでの間に消さない）。
  // 入った時点のステータス（ボードで選んだ列）は見ない。
  async enter(nodeId, projectNodeId) {
    const issue = await this.read({ nodeId });
    if (this.project.id !== projectNodeId || !issue?.item || issue.state !== "OPEN") return;
    const byUser = issue.author?.databaseId === this.config.people[this.config.user].id;
    await this.write(issue, { status: !issue.parent && !byUser ? this.config.waiting : this.config.todo });
  }

  // ステータスか開き閉じが変わった（ボードの移動・Claude の道具・閉じる・開き直す）。同じ照らしで、通れば開き閉じとステータスを
  // 揃え、通らなければ変化の前へ戻して理由をコメントする。move はボードの移動のときだけ渡す（{ project, from, to }）。
  async changed(nodeId, move) {
    const issue = await this.read({ nodeId });
    if (!issue?.item || !issue.status || (move && (move.project !== this.project.id || move.from === null || move.from === move.to))) return;
    const { done } = this.config;
    const closed = issue.state === "CLOSED";
    const reason = issue.lastClose.nodes[0]?.stateReason === "COMPLETED" ? "COMPLETED" : "NOT_PLANNED";
    const [from, to, wasClosed] = move ? [move.from, move.to, closed] : closed && issue.status !== done ? [issue.status, done, false] : !closed && issue.status === done ? [done, null, true] : [];
    if (!from) return;
    const close = to === done ? (move ? "COMPLETED" : reason) : undefined;
    const verdict = judge(this.config, from, to, { close, body: issue.body });
    if (verdict.ok) return this.write(issue, { status: to, close: to === done && !closed ? close : undefined });
    const back = wasClosed === closed ? {} : wasClosed ? { close: reason } : { reopen: true };
    await this.write(issue, { status: from, ...back, comments: [notes.back(verdict.reason, from)] });
  }

  // 作業ブランチの Pull Request: 開くと検証中へ（表で行けるのは進行中からだけ）。閉じたら、検証中のタスクだけを動かす: マージされずに
  // 閉じた → 未着手、マージされた → 完了の条件が全部チェック済みなら完了（完成）、残りがあれば残りを書いて未着手。
  async pullRequest(action, pr) {
    const { branchPrefix } = this.config.code;
    const number = pr.head.ref.startsWith(branchPrefix) && Number(pr.head.ref.slice(branchPrefix.length));
    const issue = number && (await this.read({ number }));
    if (!issue?.item || issue.state !== "OPEN") return;
    if (action !== "closed") return this.apply(issue, this.config.review);
    if (issue.status !== this.config.review) return;
    const said = (rest) => ({ comments: [notes.pullRequest(pr, rest)] });
    if (!pr.merged) return this.apply(issue, this.config.todo, said("がマージされずに閉じられました。コメントを読んでやり直してください。"));
    const done = await this.apply(issue, this.config.done, { close: "COMPLETED", ...said("をマージしました。完了にします。") });
    if (!done.ok) await this.apply(issue, this.config.todo, said(`をマージしました。${done.reason}Claude に戻します。`));
  }
}

export async function handleEvent(env, config, name, payload) {
  if (payload.sender?.login === config.gate) return;
  const gate = () => Gate.open(env, config);
  if (payload.repository?.full_name === config.code.repository)
    return name === "pull_request" && ["opened", "reopened", "closed"].includes(payload.action) ? (await gate()).pullRequest(payload.action, payload.pull_request) : undefined;
  if (name === "projects_v2_item" && payload.projects_v2_item.content_type === "Issue") {
    const item = payload.projects_v2_item;
    const change = payload.changes?.field_value;
    if (payload.action === "created") return (await gate()).enter(item.content_node_id, item.project_node_id);
    if (payload.action === "edited" && change?.field_name === config.project.statusField)
      return (await gate()).changed(item.content_node_id, { project: item.project_node_id, from: change.from?.name ?? null, to: change.to?.name ?? null });
  }
  if (name !== "issues") return;
  const g = await gate();
  if (["closed", "reopened"].includes(payload.action)) return g.changed(payload.issue.node_id);
  // 担当者・本文などが変わった: 担当者と本文の先頭だけを今の状態に揃える（手で担当者を変えても、ステータスの番へ戻る）。
  const issue = await g.read({ nodeId: payload.issue.node_id });
  if (issue?.item) await g.write(issue);
}
