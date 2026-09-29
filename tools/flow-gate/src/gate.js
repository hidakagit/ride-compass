// 遷移の処理。Webhook の出来事も回答フォームの送信も、ここの apply を通って表で照らされる。
// 1つの出来事では、タスクを1回読み（read）、書き込みを1回にまとめて書く（write）。
import { GitHub, Mutations, readTask, setField } from "./github.js";
import { opened, reconcile } from "./review.js";
import { adoptionQuestion, answererTurn, check, claude, entryFor, joinBody, normalizeBody, parseQuestion, splitBody } from "./rules.js";

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

  async read(ref) {
    const r = await readTask(this.gh, this.config, ref);
    this.project = r.project;
    this.labelIds = r.labels;
    return r.issue;
  }

  // 答える人（ask.answerer）の番の間だけ、本文の先頭にボタンとステータスの行を置く。回答待ちなら回答フォームへ、
  // 検証中なら Pull Request へ（作業ブランチで引く検索の画面へ）。答えを待つ問いは、答えるまで同じ場所に画面に出ない形で残す。
  bodyFor(issue) {
    const { verify, code, ask } = this.config;
    const { question, rest } = splitBody(issue.body);
    const turn = answererTurn(this.config, issue);
    if (turn && issue.status === verify.status) {
      const q = encodeURIComponent(`is:pr head:${code.branchPrefix}${issue.number}`);
      const url = `https://github.com/${code.repository}/pulls?q=${q}`;
      return joinBody(rest, question, { status: issue.status, text: "Pull Request を確かめ、マージするか閉じるかを決める", url, button: this.reviewUrl, alt: "確かめる" });
    }
    const q = turn && issue.status === ask.status ? currentQuestion(this.config, issue) : null;
    const url = `${this.origin}/answer?issue=${issue.number}`;
    return joinBody(rest, question, q?.parsed && { status: issue.status, text: q.parsed.text, url, button: this.buttonUrl });
  }

  // 1つのタスクへの書き込みを1回の要求で行う。want には変えたい中身だけを渡す。本文の先頭の見せ方も、書いた後の状態に
  // 合わせて同じ要求に入れる。question は答えを待つ問いを本文の先頭に置く（null なら消す。答えたとき）。
  // 閉じた子（段階）を書いたあとは、親の子が全部閉じたかを見る（ゲートは自分が閉じた出来事を捨てるので、ここで見る）。
  async write(issue, want = {}) {
    const next = {
      ...issue,
      status: "status" in want ? want.status : issue.status,
      fields: { ...issue.fields, ...(want.fields ?? {}) },
      assignees: want.assign ? { nodes: [{ id: this.config.people[want.assign].node, login: want.assign }] } : issue.assignees,
      state: want.close ? "CLOSED" : issue.state,
      body: "question" in want ? joinBody(splitBody(issue.body).rest, want.question, null) : issue.body,
    };
    const m = new Mutations();
    const statusField = this.config.project.statusField;
    if (next.status !== issue.status) {
      if (next.status === null)
        m.add("clearProjectV2ItemFieldValue", { projectId: this.project.id, itemId: issue.item, fieldId: this.project.fields[statusField].id });
      else setField(m, this.project, issue.item, statusField, next.status);
    }
    // 欄の既定値など: Project に無い欄・選択肢は書かずに飛ばす。
    for (const [name, value] of Object.entries(want.fields ?? {}))
      if (issue.fields[name] !== value && this.project.fields[name]?.options[value]) setField(m, this.project, issue.item, name, value);
    for (const body of want.comments ?? []) m.add("addComment", { subjectId: issue.id, body });

    // 割り当て・ラベル・本文・開閉は updateIssue の1つにまとめる（GitHub は mutation を1つずつ順に処理し、1つごとに時間がかかる）。
    const update = {};
    if (want.assign) {
      const id = this.config.people[want.assign].node;
      const now = issue.assignees.nodes.map((a) => a.id);
      if (now.length !== 1 || now[0] !== id) update.assigneeIds = [id];
    }
    const have = issue.labels.nodes.map((l) => l.name);
    const labels = [...new Set([...have.filter((n) => !(want.unlabels ?? []).includes(n)), ...(want.labels ?? [])])].filter((n) => this.labelIds[n]);
    if (labels.length !== have.length || labels.some((n) => !have.includes(n))) update.labelIds = labels.map((n) => this.labelIds[n]);
    const body = this.bodyFor(next);
    if (body !== normalizeBody(issue.body)) update.body = body;
    if (want.close) update.stateInput = { value: "CLOSED", stateReason: want.close };
    if (Object.keys(update).length) m.add("updateIssue", { id: issue.id, ...update });

    await m.send(this.gh);
    Object.assign(issue, next, { body, labels: { nodes: (update.labelIds ? labels : have).map((name) => ({ name })) } });
    if (issue.parent && issue.state === "CLOSED") await this.closeParent(issue.parent.number);
  }

  // 子が全部閉じた親を完了（completed）で閉じる。子が完成でも見送りでも、全部閉じれば親の仕事は終わっている。
  async closeParent(number) {
    const parent = await this.read({ number });
    if (!parent?.item || parent.state !== "OPEN" || parent.subIssues.nodes.some((s) => s.state === "OPEN")) return;
    await this.apply(parent, parent.status, this.config.done, { close: "COMPLETED", comments: ["子の issue が全部閉じたので、完了にします。"] });
  }

  // 表で照らし、通れば書く。written はステータスがもう GitHub で変わっていること（ボードの移動）。
  // next を渡さなければ表の既定の割り当てを書く。dryRun は照らすだけで書かない。
  async apply(issue, from, to, { next, labels = [], unlabels = [], written = false, dryRun = false, comments = [], close, clearQuestion } = {}) {
    const verdict = from === to ? { ok: true, rule: null } : check(this.config, from, to, issue.blockedBy.nodes);
    if (!verdict.ok) return verdict;
    if (dryRun) return { ok: true };
    const want = { labels, unlabels, comments, assign: next !== undefined ? next : (verdict.rule?.assign ?? undefined) };
    if (clearQuestion) want.question = null;
    if (!written) want.status = to;
    if (to === this.config.done && issue.state === "OPEN") want.close = close ?? "NOT_PLANNED";
    // ユーザーが確かめると決めたタスク（verify.label）は、確かめる番を表の既定ではなく答える人（ask.answerer）にする。
    const verify = this.config.verify;
    if (to === verify.status && from !== to && next === undefined && issue.labels.nodes.some((l) => l.name === verify.label))
      want.assign = this.config.ask.answerer;
    if (from !== to && to === this.config.ask.status) {
      if (!currentQuestion(this.config, issue)?.parsed) {
        want.comments = [...comments, "問いの形が崩れています（docs/conventions/flow.md「問い」）。問いを書き直してください。"];
        want.assign = claude(this.config);
      }
    }
    await this.write(issue, want);
    return { ok: true };
  }

  // 割り当て・本文などの出来事: 見せ方だけを今の状態に合わせる（問いを書いたとき・割り当て直したとき）。
  async touched(nodeId) {
    const issue = await this.read({ nodeId });
    if (issue?.item) await this.write(issue);
  }

  async enter(nodeId, projectNodeId) {
    const issue = await this.read({ nodeId });
    if (this.project.id !== projectNodeId || !issue?.item || issue.status) return;
    const entry = entryFor(this.config, issue);
    // 欄の既定値（優先度など）は、まだ値の無いものにだけ入れる。
    const fields = Object.fromEntries(Object.entries(this.config.project.defaults).filter(([name]) => !issue.fields[name]));
    const want = { status: entry.to, assign: entry.assign, fields };
    // Claude の起票は、設定の採否の問いを本文の先頭に置いて回答待ちにする（問いは bin/ask.js と同じ置き場）。
    if (entry.adoption) want.question = adoptionQuestion(this.config).trim();
    await this.write(issue, want);
  }

  async moved(nodeId, projectNodeId, from, to) {
    const issue = await this.read({ nodeId });
    if (this.project.id !== projectNodeId || !issue?.item || from === to) return;
    const r = await this.apply(issue, from, to, { written: true });
    if (!r.ok) await this.write(issue, { status: from, comments: [`${r.reason}「${from ?? "（無し）"}」へ戻しました。`] });
  }

  async closed(nodeId) {
    const issue = await this.read({ nodeId });
    if (!issue?.item || issue.status === this.config.done) return;
    if (!check(this.config, issue.status, this.config.done).ok) return;
    await this.write(issue, { status: this.config.done });
  }

  async reopened(nodeId) {
    const issue = await this.read({ nodeId });
    if (!issue?.item || issue.status !== this.config.done) return;
    await this.write(issue, {
      close: issue.lastClose.nodes[0]?.stateReason ?? "NOT_PLANNED",
      comments: [`「${this.config.done}」からは戻せません（遷移の表に無い）。閉じ直しました。続きは新しい issue にしてください。`],
    });
  }
}

// 今の問い: 本文の先頭に置いた問い（bin/ask.js か、入口の採否の問いならゲートが書く）。id は問いの中身から作り、回答フォームを
// 開いたあとに問いが書き直されたかを見分けるのに使う。
export function currentQuestion(config, issue) {
  const { question } = splitBody(issue.body);
  return question ? { id: questionId(question), body: question, parsed: parseQuestion(config, question) } : null;
}

function questionId(text) {
  let h = 0;
  for (const c of text) h = (h * 31 + c.codePointAt(0)) >>> 0;
  return h.toString(36);
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
  if (payload.action === "closed") return gate.closed(payload.issue.node_id);
  if (payload.action === "reopened") return gate.reopened(payload.issue.node_id);
  return gate.touched(payload.issue.node_id);
}

// コードのリポジトリの出来事: Pull Request が開いた・閉じた（マージ・マージせず）ときはその作業ブランチのタスクを、master の CI が
// 終わったときは検証中のタスクをすべて、今の状態に合わせて動かす。
function codeEvent(env, config, origin, name, payload) {
  const { branchPrefix, base } = config.code;
  if (name === "pull_request" && ["opened", "reopened", "closed"].includes(payload.action)) {
    const ref = payload.pull_request.head.ref;
    const number = ref.startsWith(branchPrefix) && Number(ref.slice(branchPrefix.length));
    if (!number) return "作業ブランチの Pull Request ではない";
    return payload.action === "closed" ? reconcile(env, config, origin, [number]) : opened(env, config, origin, number);
  }
  if (name === "workflow_run" && payload.action === "completed" && payload.workflow_run.head_branch === base) return reconcile(env, config, origin);
  return "対象外の出来事";
}
