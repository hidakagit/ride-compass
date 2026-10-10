// ゲート: GitHub の出来事と見回りの頼みを受け、事実を読んで表（rules.js: decide）でステータスを決めて書く。担当はステータスを書かない。
import { addComment, blockedOpen, dialogBoard, GitHub, readActive, readPull, readTask, setField, typeIds } from "./github.js";
import { bodyRest, decide, gateQuestion, normalize, parseAnswer, remaining, runOf, SCAN, takeAnswer, unanswered, withButton } from "./rules.js";

const PR_ACTIONS = ["opened", "reopened", "closed", "ready_for_review", "converted_to_draft", "synchronize"];
const NO_RETYPE = "種類は作るときに決め、あとから変えられません。";
const refused = (left) => `完成にするには次が残っています。\n\n${left.map((l) => `- ${l}`).join("\n")}`;

export class Gate {
  // App の名義で読み書きする（置き場とコードのリポジトリはインストールが別）。
  static async open(env, config) {
    const gate = new Gate();
    Object.assign(gate, { env, config, gh: await GitHub.asApp(env, config.repository) });
    return gate;
  }

  code() {
    return GitHub.asApp(this.env, this.config.code.repository);
  }

  // 答えていない問いを見分けるため、コメントを SCAN 件読む。
  async read(ref) {
    const r = await readTask(this.gh, this.config, ref, { comments: SCAN });
    this.project = r.project;
    return r.issue;
  }

  // 表の事実を読む（rules.js: decide の f）。持たれている間・保留の間は PR を読まない。
  async facts(issue, { released, unhold = false, entry = false } = {}) {
    const { config } = this;
    const bodies = issue.comments.nodes.map((c) => c.body);
    const adopt = entry && issue.author?.databaseId !== config.people[config.user].id && !issue.parent && !config.todoTypes.includes(issue.issueType?.name)
      && !bodies.some((b) => normalize(b).startsWith("## 問い"));
    const f = { state: issue.state, status: issue.status, unhold, released: Boolean(released), adopt, asked: unanswered(bodies), body: issue.body,
      blocked: blockedOpen(issue), start: issue.fields[config.project.startField] ?? null, now: new Date(), holder: null, pr: null, merged: false };
    if (issue.state !== "OPEN") return f;
    const code = await this.code();
    this.runs = (await readActive((p) => code.rest("GET", p), config)).filter((r) => r.number === issue.number);
    f.holder = this.runs[0]?.kind ?? null;
    if (f.holder || (issue.status === config.status.hold && !unhold)) return f;
    const { open, merged } = await readPull(code, config, `${config.code.branchPrefix}${issue.number}`);
    return Object.assign(f, { pr: open, merged });
  }

  // 事実から決めて書く。want はほかに一緒に書くもの（write の形）。
  async settle(issue, options = {}, want = {}) {
    const f = await this.facts({ ...issue, body: want.body ?? issue.body }, options);
    const d = decide(this.config, f);
    const asks = d.ask ? [gateQuestion(d.ask, options.released)] : [];
    await this.write(issue, { ...want, status: d.status, close: d.close ?? want.close, comments: [...(want.comments ?? []), ...asks], ready: d.ready ? f.pr.id : undefined });
  }

  async settleNumber(number, options) {
    const issue = number && (await this.read({ number }));
    if (issue?.item) await this.settle(issue, options);
  }

  // want に変えたいものだけを渡す（status・fields（Status 以外の欄の名前 → 値）・comments・close・reopen・body・type（種類の id か null）・
  // ready（レビュー可能にする PR の id）・cancel（取り消す担当の実行の id））。本文の先頭のボタンは答えの無い問いがある間だけ置き、問いの
  // コメントより先に書く（問いの通知から開いた時点でボタンがある）。担当者は回答待ちと保留のときだけユーザー。
  async write(issue, want = {}) {
    const { config } = this;
    const status = want.status ?? issue.status;
    const state = want.close ? "CLOSED" : want.reopen ? "OPEN" : issue.state;
    const comments = want.comments ?? [];
    const rest = bodyRest(want.body ?? issue.body);
    const asked = state === "OPEN" && unanswered([...issue.comments.nodes.map((c) => c.body), ...comments]);
    const body = asked ? withButton(rest, `${config.urls.form}/answer?issue=${issue.number}`, `${config.urls.gate}/button.svg`) : rest;
    const ops = [];
    if (issue.item && status !== issue.status) ops.push(setField(this.project, issue.item, config.project.statusField, status));
    for (const [name, value] of Object.entries(want.fields ?? {})) ops.push(setField(this.project, issue.item, name, value));
    if (want.reopen) ops.push(["reopenIssue", { issueId: issue.id }]);
    const update = {};
    const owners = state === "OPEN" && [config.status.waiting, config.status.hold].includes(status) ? [config.people[config.user].node] : [];
    if (owners.join() !== issue.assignees.nodes.map((a) => a.id).join()) update.assigneeIds = owners;
    if (body !== normalize(issue.body)) update.body = body;
    if (want.close && issue.state === "OPEN") update.stateInput = { value: "CLOSED", stateReason: want.close };
    if ("type" in want) update.issueTypeId = want.type;
    if (Object.keys(update).length) ops.push(["updateIssue", { id: issue.id, ...update }]);
    ops.push(...comments.map((c) => addComment(issue.id, c)));
    await this.gh.write(ops);
    if (want.ready) await (await this.code()).write([["markPullRequestReadyForReview", { pullRequestId: want.ready }]]);
    for (const id of want.cancel ?? []) await (await this.code()).rest("POST", `/repos/${config.code.repository}/actions/runs/${id}/cancel`);
  }

  // issue が作られた: 種類が対話作業なら対話作業のボードへ入れるだけ。ほかは Actions のボードへ入れて入口を通す。
  async place(nodeId) {
    const issue = await this.read({ nodeId });
    if (issue?.state !== "OPEN") return;
    if (issue.issueType?.name === this.config.dialog.type) {
      if (!issue.dialog) await this.gh.write([["addProjectV2ItemById", { projectId: (await dialogBoard(this.gh, this.config)).id, contentId: issue.id }]]);
      return;
    }
    if (!issue.item) await this.gh.write([["addProjectV2ItemById", { projectId: this.project.id, contentId: issue.id }]]);
    await this.enter(nodeId, this.project.id);
  }

  // Actions のボードに入った: 入口。段階は優先度の欄が空なら親の優先度を継ぐ。ほかの欄は書かない（誰も決めていない欄は空のまま見せ、起票の
  // 直後に入れた値を、読んでから書くまでの間に消さない）。
  async enter(nodeId, projectNodeId) {
    const issue = await this.read({ nodeId });
    if (this.project.id !== projectNodeId || !issue?.item || issue.state !== "OPEN" || issue.issueType?.name === this.config.dialog.type) return;
    const priority = this.config.project.priorityField;
    const inherited = issue.parent && !issue.fields[priority] ? (await readTask(this.gh, this.config, { number: issue.parent.number })).issue?.fields[priority] : null;
    await this.settle(issue, { entry: true }, { fields: inherited ? { [priority]: inherited } : {} });
  }

  // ユーザーのボードの移動: 保留へ入れるのと完了は受け（保留へ入れたら持っている担当の実行を取り消す。完成は残りが無いときだけ）、ほかは表で決め直す。
  async moved(nodeId, projectNodeId, from, to) {
    const issue = await this.read({ nodeId });
    if (!issue?.item || this.project.id !== projectNodeId || from === null || from === to) return;
    const S = this.config.status;
    if (to === S.hold) {
      await this.facts(issue);
      return this.write(issue, { status: S.hold, cancel: this.runs.map((r) => r.id) });
    }
    const left = to === S.done ? remaining(issue.body) : [];
    if (to === S.done && !left.length) return this.write(issue, { status: S.done, close: "COMPLETED" });
    await this.settle(issue, { unhold: from === S.hold }, { comments: left.length ? [refused(left)] : [] });
  }

  // 閉じた・開き直した: 完成は残りがあれば開き直して決め直す。見送りはいつでも完了。完了からは開き直せない（続きは新しい issue）。
  async reopened(nodeId) {
    const issue = await this.read({ nodeId });
    if (!issue?.item) return;
    const reason = issue.lastClose.nodes[0]?.stateReason === "COMPLETED" ? "COMPLETED" : "NOT_PLANNED";
    const left = remaining(issue.body);
    if (issue.state === "CLOSED" && reason === "COMPLETED" && left.length) return this.settle({ ...issue, state: "OPEN" }, {}, { reopen: true, comments: [refused(left)] });
    if (issue.state === "CLOSED") return this.write(issue, { status: this.config.status.done });
    return issue.status === this.config.status.done ? this.write(issue, { close: reason }) : this.settle(issue);
  }

  // コメントが書かれた: 問いなら決め直す。答え（最新の問いへのもの）なら決定を受ける: 見送りは閉じ、保留は保留、続けるは本文へ写して表で決め直す。
  async commented(nodeId, text) {
    const issue = await this.read({ nodeId });
    if (!issue?.item || issue.state !== "OPEN") return;
    const bodies = issue.comments.nodes.map((c) => normalize(c.body));
    const answer = parseAnswer(text);
    const at = bodies.lastIndexOf(normalize(text));
    if (!answer || at < 1 || !unanswered(bodies.slice(0, at))) return /^## 問い/.test(normalize(text)) ? this.settle(issue) : undefined;
    if (answer.decision === "見送り") return this.write(issue, { status: this.config.status.done, close: "NOT_PLANNED" });
    if (answer.decision === "保留") return this.write(issue, { status: this.config.status.hold });
    const body = takeAnswer(issue.body, answer);
    await this.settle(issue, { unhold: true }, { body });
  }

  // 種類が変わった: 対話作業の境目（どちらのボードに載っているか）をまたいだら元の種類へ戻して1行書く。またがない変更は通す。
  async retyped(nodeId) {
    const issue = await this.read({ nodeId });
    const { dialog } = this.config;
    if (issue?.state !== "OPEN" || (!issue.dialog && !issue.item) || (issue.issueType?.name === dialog.type) === issue.dialog) return;
    let back = dialog.type;
    if (!issue.dialog) {
      const events = (await this.gh.gql(`query TypeEvents($id: ID!) { node(id: $id) { ... on Issue { timelineItems(last: 20, itemTypes: [ISSUE_TYPE_ADDED_EVENT, ISSUE_TYPE_CHANGED_EVENT, ISSUE_TYPE_REMOVED_EVENT]) {
        nodes { __typename ... on IssueTypeAddedEvent { issueType { name } } ... on IssueTypeChangedEvent { prevIssueType { name } issueType { name } }
        ... on IssueTypeRemovedEvent { issueType { name } } } } } } }`, { id: issue.id })).node.timelineItems.nodes;
      back = events.toReversed().map((e) => (e.__typename === "IssueTypeChangedEvent" ? e.prevIssueType : e.__typename === "IssueTypeRemovedEvent" ? e.issueType : null)?.name)
        .find((name) => name && name !== dialog.type) ?? null;
    }
    await this.write(issue, { type: back && (await typeIds(this.gh, this.config))[back], comments: [NO_RETYPE] });
  }
}

export async function handleEvent(env, config, name, payload) {
  if (payload.sender?.login === config.gate) return;
  const gate = () => Gate.open(env, config);
  const { branchPrefix, repository: code } = config.code;
  const branchNumber = (ref) => (ref?.startsWith(branchPrefix) ? Number(ref.slice(branchPrefix.length)) : null);
  if (payload.repository?.full_name === code) {
    if (name === "workflow_run") {
      const run = payload.workflow_run;
      const mine = run.path?.endsWith(`/${config.coordinator.workflow}`);
      const done = payload.action === "completed";
      if (!mine && !done) return;
      const released = mine && done ? { url: run.html_url, conclusion: run.conclusion } : undefined;
      return (await gate()).settleNumber(mine ? Number(runOf(run.display_title)[0]) : branchNumber(run.head_branch), { released });
    }
    if (name === "pull_request" && PR_ACTIONS.includes(payload.action)) return (await gate()).settleNumber(branchNumber(payload.pull_request.head.ref));
    return;
  }
  if (name === "repository_dispatch" && payload.action === "recheck" && payload.repository?.full_name === config.repository) return (await gate()).settleNumber(Number(payload.client_payload?.number));
  if (name === "projects_v2_item" && payload.projects_v2_item.content_type === "Issue") {
    const item = payload.projects_v2_item;
    const change = payload.changes?.field_value;
    if (payload.action === "created") return (await gate()).enter(item.content_node_id, item.project_node_id);
    if (payload.action === "edited" && change?.field_name === config.project.statusField)
      return (await gate()).moved(item.content_node_id, item.project_node_id, change.from?.name ?? null, change.to?.name ?? null);
    return;
  }
  if (name === "issue_comment" && payload.action === "created") return (await gate()).commented(payload.issue.node_id, payload.comment.body);
  if (name !== "issues") return;
  const g = await gate();
  const id = payload.issue.node_id;
  if (payload.action === "opened") return g.place(id);
  if (["typed", "untyped"].includes(payload.action)) return g.retyped(id);
  if (["closed", "reopened"].includes(payload.action)) return g.reopened(id);
  // 担当者・本文などが変わった: 担当者と本文の先頭だけを今の状態に揃える。
  const issue = await g.read({ nodeId: id });
  if (issue?.item) await g.write(issue);
}
