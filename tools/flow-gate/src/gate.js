// 遷移の処理。Webhook の出来事も回答フォームの送信も、ここの apply を通って表で照らされる。
// 1つの出来事では、タスクを1回読み（read）、書き込みを1回にまとめて書く（write）。
import { GitHub, Mutations, readTask } from "./github.js";
import { reconcile } from "./review.js";
import { adoptionQuestion, answers, check, entryFor, parseQuestion, personById, withBanner, withoutBanner } from "./rules.js";

const normalize = (body) => (body ?? "").replace(/\r\n/g, "\n");

export class Gate {
  static async open(env, config, origin) {
    const gate = new Gate();
    gate.config = config;
    gate.origin = origin;
    // ボタンの画像は GitHub が中継して取りに来るので、Access の外の Worker（GATE_ORIGIN）から返す。
    gate.buttonUrl = `${env.GATE_ORIGIN ?? origin}/button.svg`;
    gate.reviewUrl = `${env.GATE_ORIGIN ?? origin}/review.svg`;
    gate.gh = await GitHub.asApp(env, config.installation);
    return gate;
  }

  get gateLogin() {
    return this.config.gate.replace(/\[bot\]$/, "");
  }

  async read(ref) {
    const r = await readTask(this.gh, this.config, ref);
    this.project = r.project;
    this.labelIds = r.labels;
    return r.issue;
  }

  // 答えが要る（採否待ち・回答待ちで、答えの無い問いがある）間だけ、本文の先頭にステータス・問い・リンクの1行を置く。
  // ユーザーが確かめる番の検証中の間は、同じ場所に Pull Request を開くボタンを置く（作業ブランチで引く検索の画面へ）。
  bodyFor(issue) {
    const { verify, code, ask } = this.config;
    const reviewer = this.config.people[ask.answerer].node;
    if (issue.state === "OPEN" && issue.status === verify.status && issue.assignees.nodes.some((a) => a.id === reviewer)) {
      const q = encodeURIComponent(`is:pr head:${code.branchPrefix}${issue.number}`);
      const url = `https://github.com/${code.repository}/pulls?q=${q}`;
      return withBanner(issue.body, issue.status, { text: "Pull Request を確かめ、マージするか閉じるかを決める", url, button: this.reviewUrl, alt: "確かめる" });
    }
    const q = this.config.ask.statuses.includes(issue.status) ? currentQuestion(this.config, issue) : null;
    const open = issue.state === "OPEN" && q?.parsed && !issue.comments.nodes.some((c) => answers(c.body, q.url));
    const url = `${this.origin}/answer?issue=${issue.number}`;
    return open ? withBanner(issue.body, issue.status, { text: q.parsed.text, url, button: this.buttonUrl }) : withoutBanner(issue.body);
  }

  // 1つのタスクへの書き込みを1回の要求で行う。want には変えたい中身だけを渡す。見せ方（ステータスのラベルは Project の
  // Status と同じ1つだけ、本文の先頭の1行は答えが要る間だけ）も、書いた後の状態に合わせて同じ要求に入れる。
  // ステータスのラベルを置くのは、スマホの issue の画面が Project の欄を出さず、ラベルなら一覧・詳細・絞り込みで見えるため。
  async write(issue, want = {}) {
    const added = (want.comments ?? []).map((body) => ({ body, url: null, author: { login: this.gateLogin } }));
    const next = {
      ...issue,
      status: "status" in want ? want.status : issue.status,
      assignees: want.assign ? { nodes: [{ id: this.config.people[want.assign].node, login: want.assign }] } : issue.assignees,
      state: want.close ? "CLOSED" : want.reopen ? "OPEN" : issue.state,
      comments: { nodes: [...issue.comments.nodes, ...added, ...(want.seen ?? [])] },
    };
    const m = new Mutations();
    if (next.status !== issue.status) {
      const at = { projectId: this.project.id, itemId: issue.item, fieldId: this.project.field };
      if (next.status === null) m.add("clearProjectV2ItemFieldValue", at);
      else m.add("updateProjectV2ItemFieldValue", { ...at, value: { singleSelectOptionId: this.project.options[next.status] } });
    }
    for (const body of want.comments ?? []) m.add("addComment", { subjectId: issue.id, body });
    for (const id of want.closeOthers ?? []) m.add("closeIssue", { issueId: id, stateReason: "COMPLETED" });

    // 割り当て・ラベル・本文・開閉は updateIssue の1つにまとめる（GitHub は mutation を1つずつ順に処理し、1つごとに時間がかかる）。
    const update = {};
    if (want.assign) {
      const id = this.config.people[want.assign].node;
      const now = issue.assignees.nodes.map((a) => a.id);
      if (now.length !== 1 || now[0] !== id) update.assigneeIds = [id];
    }
    const prefix = this.config.statusLabelPrefix;
    const statusLabel = next.status ? `${prefix}${next.status}` : null;
    const have = issue.labels.nodes.map((l) => l.name);
    const labels = [...new Set([...have.filter((n) => !n.startsWith(prefix)), ...(want.labels ?? []), ...(statusLabel ? [statusLabel] : [])])].filter(
      (n) => this.labelIds[n],
    );
    if (labels.length !== have.length || labels.some((n) => !have.includes(n))) update.labelIds = labels.map((n) => this.labelIds[n]);
    const body = this.bodyFor(next);
    if (body !== normalize(issue.body)) update.body = body;
    if (want.close) update.stateInput = { value: "CLOSED", stateReason: want.close };
    if (want.reopen) update.stateInput = { value: "OPEN" };
    if (Object.keys(update).length) m.add("updateIssue", { id: issue.id, ...update });

    await m.send(this.gh);
    Object.assign(issue, next, { body, labels: { nodes: (update.labelIds ? labels : have).map((name) => ({ name })) } });
  }

  // 表で照らし、通れば書く。written はステータスがもう GitHub で変わっていること（ボードの移動）。
  // next を渡さなければ表の既定の割り当てを書く。dryRun は照らすだけで書かない。seen は回答フォームが渡す
  // この直前に書いた答え（本文の先頭の1行を消すかを決めるのに使う）。
  async apply(issue, from, to, { next, labels = [], written = false, dryRun = false, seen, comments = [], close } = {}) {
    const verdict = from === to ? { ok: true, rule: null } : check(this.config, from, to, issue.blockedBy.nodes);
    if (!verdict.ok) return verdict;
    const missing = labels.filter((n) => !this.labelIds[n]);
    if (missing.length) return { ok: false, reason: `ラベル「${missing.join("」「")}」が GitHub にありません。` };
    if (dryRun) return { ok: true };
    const want = { labels, seen, comments, assign: next !== undefined ? next : (verdict.rule?.assign ?? undefined) };
    if (!written) want.status = to;
    if (to === this.config.done && issue.state === "OPEN") want.close = close ?? "NOT_PLANNED";
    // ユーザーが確かめると決めたタスク（verify.label）は、確かめる番を表の既定ではなく答える人（ask.answerer）にする。
    const verify = this.config.verify;
    if (to === verify.status && from !== to && next === undefined && issue.labels.nodes.some((l) => l.name === verify.label))
      want.assign = this.config.ask.answerer;
    if (from !== to && this.config.ask.statuses.includes(to) && to !== this.config.adoption.status) {
      if (!currentQuestion(this.config, issue)?.parsed) {
        want.comments = [...comments, "問いの形が崩れています（docs/conventions/flow.md「問い」）。問いを書き直してください。"];
        want.assign = this.config.ask.askers[0];
      }
    }
    await this.write(issue, want);
    return { ok: true };
  }

  // 割り当て・本文・ラベルなどの出来事: 見せ方だけを今の状態に合わせる（問い直したとき・ラベルを手で付け替えたとき）。
  async touched(nodeId) {
    const issue = await this.read({ nodeId });
    if (issue?.item && !issue.parent) await this.write(issue);
  }

  async enter(nodeId, projectNodeId) {
    const issue = await this.read({ nodeId });
    if (this.project.id !== projectNodeId || !issue?.item || issue.parent || issue.status) return;
    const entry = entryFor(this.config, issue.author.databaseId);
    await this.write(issue, { status: entry.to, assign: entry.assign });
  }

  async moved(nodeId, projectNodeId, from, to) {
    const issue = await this.read({ nodeId });
    if (this.project.id !== projectNodeId || !issue?.item || issue.parent || from === to) return;
    const r = await this.apply(issue, from, to, { written: true });
    if (!r.ok) await this.write(issue, { status: from, comments: [`${r.reason}「${from ?? "（無し）"}」へ戻しました。`] });
  }

  async closed(nodeId, reason) {
    const issue = await this.read({ nodeId });
    if (!issue?.item || issue.parent || issue.status === this.config.done) return;
    if (!check(this.config, issue.status, this.config.done).ok) return;
    const stage = reason === "completed" && issue.subIssues.nodes.find((s) => s.state === "OPEN");
    if (!stage) return this.write(issue, { status: this.config.done });
    await this.write(issue, { status: this.config.nextStage.to, assign: this.config.nextStage.assign, reopen: true, closeOthers: [stage.id] });
  }

  async reopened(nodeId) {
    const issue = await this.read({ nodeId });
    if (!issue?.item || issue.parent || issue.status !== this.config.done) return;
    await this.write(issue, {
      close: issue.lastClose.nodes[0]?.stateReason ?? "NOT_PLANNED",
      comments: [`「${this.config.done}」からは戻せません（遷移の表に無い）。閉じ直しました。続きは新しい issue にしてください。`],
    });
  }
}

export const ADOPTION_ID = "adoption";

// 今の問い: 問いを書ける者（askers）かゲートが書いた、1行目が「## 問い」のコメントのうち最新の1つ。
// 採否待ちでそれが無ければ、設定の採否の問い（決まった中身なのでコメントには書かない）。
export function currentQuestion(config, issue) {
  const gateLogin = config.gate.replace(/\[bot\]$/, "");
  const q = [...issue.comments.nodes]
    .reverse()
    .find(
      (c) =>
        c.body.startsWith("## 問い") &&
        (c.author?.login === gateLogin || config.ask.askers.includes(personById(config, c.author?.databaseId))),
    );
  if (q) return { ...q, parsed: parseQuestion(config, q.body) };
  if (issue.status !== config.adoption.status) return null;
  const body = adoptionQuestion(config);
  return { id: ADOPTION_ID, url: `${issue.url}#採否`, body, parsed: parseQuestion(config, body) };
}

export async function handleEvent(env, config, origin, name, payload) {
  if (payload.sender?.login === config.gate) return "ゲート自身の出来事";
  if (payload.repository?.full_name === config.code.repository) return codeEvent(env, config, origin, name, payload);
  if (name === "projects_v2_item") {
    const item = payload.projects_v2_item;
    const change = payload.changes?.field_value;
    if (item.content_type !== "Issue") return "対象外の件";
    if (payload.action === "created") return (await Gate.open(env, config, origin)).enter(item.content_node_id, item.project_node_id);
    if (payload.action === "edited" && change?.field_name === config.project.statusField)
      return (await Gate.open(env, config, origin)).moved(item.content_node_id, item.project_node_id, change.from?.name ?? null, change.to?.name ?? null);
    return "対象外の欄";
  }
  if (name !== "issues") return "対象外の出来事";
  const gate = await Gate.open(env, config, origin);
  if (payload.action === "closed") return gate.closed(payload.issue.node_id, payload.issue.state_reason);
  if (payload.action === "reopened") return gate.reopened(payload.issue.node_id);
  return gate.touched(payload.issue.node_id);
}

// コードのリポジトリの出来事: Pull Request が閉じた（マージ・マージせず）ときはその作業ブランチのタスクを、master の CI が
// 終わったときは検証中のタスクをすべて、今の状態に合わせて動かす。
function codeEvent(env, config, origin, name, payload) {
  const { branchPrefix, base } = config.code;
  if (name === "pull_request" && payload.action === "closed") {
    const number = payload.pull_request.head.ref.startsWith(branchPrefix) && Number(payload.pull_request.head.ref.slice(branchPrefix.length));
    return number ? reconcile(env, config, origin, [number]) : "作業ブランチの Pull Request ではない";
  }
  if (name === "workflow_run" && payload.action === "completed" && payload.workflow_run.head_branch === base) return reconcile(env, config, origin);
  return "対象外の出来事";
}
