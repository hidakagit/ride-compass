// 遷移の処理。Webhook の出来事も回答フォームの送信も、ここの apply を通って表で照らされる。
// 1つの出来事では、タスクを1回読み（read）、書き込みを1回にまとめて書く（write）。
import { GitHub, Mutations, readTask, setField } from "./github.js";
import { pullRequest } from "./review.js";
import { check, entryFor, joinBody, normalizeBody, openChildren, ownerOf, parseQuestion, questionBody, remaining, splitBody, userTurn } from "./rules.js";

export class Gate {
  // env.GITHUB_TOKEN があればその名義で読み書きする（手元・CI で開いた issue を揃える道具。src/refresh.js）。無ければ App の名義。
  static async open(env, config) {
    const gate = new Gate();
    gate.config = config;
    gate.gh = env.GITHUB_TOKEN ? new GitHub(env.GITHUB_TOKEN) : await GitHub.asApp(env, config.installation);
    return gate;
  }

  async read(ref, options) {
    const r = await readTask(this.gh, this.config, ref, options);
    this.project = r.project;
    this.labelIds = r.labels;
    return r.issue;
  }

  // ユーザーの番の間だけ、本文の先頭に回答フォームへのボタンとステータスの行を置く。答えを待つ問いは、答えるまで
  // 同じ場所に画面に出ない形で残す。
  bodyFor(issue) {
    const { question, rest } = splitBody(issue.body);
    if (!userTurn(this.config, issue)) return joinBody(rest, question, null);
    // ボタンの画像は GitHub が中継して取りに来るので、Access の外の Worker（urls.gate）から返す。
    const { gate, form } = this.config.urls;
    const url = `${form}/answer?issue=${issue.number}`;
    return joinBody(rest, question, { status: issue.status, text: currentQuestion(this.config, issue).parsed.text, url, image: `${gate}/button.svg` });
  }

  // 1つのタスクへの書き込みを1回の要求で行う。want には変えたい中身だけを渡す。担当者はステータスから決め（ownerOf）、
  // 本文の先頭の見せ方も書いた後の状態に合わせて同じ要求に入れる。question は答えを待つ問いを本文の先頭に置く（null なら消す）。
  // 閉じた子（段階）を書いたあとは、親の子が全部閉じたかを見る（ゲートは自分が閉じた出来事を捨てるので、ここで見る）。
  async write(issue, want = {}, reread = true) {
    const next = {
      ...issue,
      status: "status" in want ? want.status : issue.status,
      fields: { ...issue.fields, ...(want.fields ?? {}) },
      state: want.close ? "CLOSED" : want.reopen ? "OPEN" : issue.state,
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
    if (want.reopen) m.add("reopenIssue", { issueId: issue.id });

    // 割り当て・ラベル・本文・閉じるは updateIssue の1つにまとめる（GitHub は mutation を1つずつ順に処理し、1つごとに時間がかかる）。
    const update = {};
    const owner = ownerOf(this.config, next);
    if (owner) {
      const id = this.config.people[owner].node;
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

    try {
      await m.send(this.gh);
    } catch (e) {
      // 同じ issue の出来事（例: bin/ask.js の本文とステータスの書き込み）は別々に並んで処理され、先に同じ担当者を入れた
      // 書き込みがあると GitHub は updateIssue を丸ごと断る。updateIssue より前の書き込みは通っているので、読み直して
      // updateIssue に入れる分だけを今の状態から書き直す。
      if (!reread || !update.assigneeIds || !/Assignments is invalid/.test(e.message)) throw e;
      const fresh = await this.read({ nodeId: issue.id });
      const { labels, unlabels, close } = want;
      await this.write(fresh, { labels, unlabels, close, ...("question" in want ? { question: want.question } : {}) }, false);
      Object.assign(issue, fresh);
      return;
    }
    Object.assign(issue, next, {
      body,
      labels: { nodes: (update.labelIds ? labels : have).map((name) => ({ name })) },
      assignees: update.assigneeIds ? { nodes: [{ id: update.assigneeIds[0], login: owner }] } : issue.assignees,
    });
    if (issue.parent && issue.state === "CLOSED") await this.closeParent(issue.parent.number);
  }

  // 子が全部閉じた親を完了（completed）で閉じる。子が完成でも見送りでも、全部閉じれば親の仕事は終わっている。
  async closeParent(number) {
    const parent = await this.read({ number });
    if (!parent?.item || parent.state !== "OPEN" || openChildren(parent.subIssues.nodes).length) return;
    await this.apply(parent, parent.status, this.config.done, { on: "閉じた", close: "COMPLETED", comments: ["子の issue が全部閉じたので、完了にします。"] });
  }

  // 出来事 on で表を照らし、通れば書く。written はステータスがもう GitHub で変わっていること（Claude の道具の書き込み）。
  // dryRun は照らすだけで書かない。
  async apply(issue, from, to, { on, labels = [], unlabels = [], written = false, dryRun = false, comments = [], close, clearQuestion } = {}) {
    const verdict = check(this.config, from, to, { on, blockers: issue.blockedBy.nodes });
    if (!verdict.ok) return verdict;
    if (dryRun) return { ok: true };
    const want = { labels, unlabels, comments };
    if (clearQuestion) want.question = null;
    if (!written) want.status = to;
    if (to === this.config.done && issue.state === "OPEN") want.close = close ?? "NOT_PLANNED";
    await this.write(issue, want);
    return { ok: true };
  }

  // 割り当て・本文・ラベルなどの出来事: 担当者と見せ方だけを今の状態に合わせる（手で担当者を変えても、ステータスの番へ戻る）。
  async touched(nodeId) {
    const issue = await this.read({ nodeId });
    if (issue?.item) await this.write(issue);
  }

  // Project に入った: 入口の行でステータスを決める。入った時点のステータス（ボードで選んだ列）は見ない。
  async enter(nodeId, projectNodeId) {
    const issue = await this.read({ nodeId });
    if (this.project.id !== projectNodeId || !issue?.item || issue.state !== "OPEN") return;
    const entry = entryFor(this.config, issue);
    // 欄の既定値（優先度など）は、まだ値の無いものにだけ入れる。
    const fields = Object.fromEntries(Object.entries(this.config.project.defaults).filter(([name]) => !issue.fields[name]));
    const want = { status: entry.to, fields };
    // Claude の起票は、採否の問いを本文の先頭に置いて回答待ちにする（問いは bin/ask.js と同じ置き場）。
    if (entry.question) want.question = questionBody(entry.question);
    await this.write(issue, want);
  }

  // ステータスが書き換わった: Claude の出来事（道具の書き込み）で表にあるものだけを通し、ほか（ボードの手での移動など）は
  // 戻す。ユーザーの判断は回答フォームで届く。入った直後の「無し」からの変化は入口が決めるので見ない。
  async moved(nodeId, projectNodeId, from, to, sender) {
    const issue = await this.read({ nodeId });
    if (this.project.id !== projectNodeId || !issue?.item || from === to || from === null) return;
    const by = sender === this.config.claude ? "claude" : null;
    const verdict = by ? check(this.config, from, to, { by, blockers: issue.blockedBy.nodes }) : { ok: false, reason: "ステータスは回答フォームで答えて動かします。" };
    if (verdict.ok && verdict.rule.on === "問い" && !parseQuestion(splitBody(issue.body).question ?? "")) {
      verdict.ok = false;
      verdict.reason = "問いが本文の先頭に無いため、回答待ちにできません（bin/ask.js で問います）。";
    }
    if (verdict.ok) await this.write(issue);
    else await this.write(issue, { status: from, comments: [`${verdict.reason}「${from}」へ戻しました。`] });
  }

  // 閉じた: 完成（completed）で閉じるなら、完了の条件が全部チェック済みでユーザーの確認が残っていないときだけ通す。
  // 残っていれば開き直す（ユーザーが完成を決めるのは回答フォームの「完成」）。見送りで閉じたものはそのまま完了にする。
  async closed(nodeId) {
    const issue = await this.read({ nodeId });
    if (!issue?.item || issue.status === this.config.done || !check(this.config, issue.status, this.config.done, { on: "閉じた" }).ok) return;
    const left = issue.lastClose.nodes[0]?.stateReason === "COMPLETED" ? remaining(this.config, issue) : [];
    if (!left.length) return this.write(issue, { status: this.config.done });
    await this.write(issue, {
      reopen: true,
      comments: [`完成として閉じるには、次が残っています。開き直しました。\n\n${left.map((l) => `- ${l}`).join("\n")}`],
    });
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

// 今の問い: 本文の先頭に置いた問い（bin/ask.js か、入口の採否の問いならゲートが書く）。本文に読める問いが無ければ、
// ステータスごとの決まった問い（flow.config.json: questions）。id は問いの中身から作り、回答フォームを開いたあとに
// 問いが書き直されたかを見分けるのに使う。
export function currentQuestion(config, issue) {
  const written = splitBody(issue.body).question;
  const body = written && parseQuestion(written) ? written : questionBody(config.questions[issue.status] ?? config.questions.default);
  return { id: questionId(body), body, parsed: parseQuestion(body) };
}

function questionId(text) {
  let h = 0;
  for (const c of text) h = (h * 31 + c.codePointAt(0)) >>> 0;
  return h.toString(36);
}

export async function handleEvent(env, config, name, payload) {
  if (payload.sender?.login === config.gate) return "ゲート自身の出来事";
  if (payload.repository?.full_name === config.code.repository) {
    if (name === "pull_request" && ["opened", "reopened", "closed"].includes(payload.action))
      return pullRequest(env, config, payload.action, payload.pull_request);
    return "対象外の出来事";
  }
  if (name === "projects_v2_item") {
    const item = payload.projects_v2_item;
    const change = payload.changes?.field_value;
    if (item.content_type !== "Issue") return "対象外の件";
    if (payload.action === "created") return (await Gate.open(env, config)).enter(item.content_node_id, item.project_node_id);
    if (payload.action === "edited" && change?.field_name === config.project.statusField)
      return (await Gate.open(env, config)).moved(item.content_node_id, item.project_node_id, change.from?.name ?? null, change.to?.name ?? null, payload.sender?.login);
    return "対象外の欄";
  }
  if (name !== "issues") return "対象外の出来事";
  const gate = await Gate.open(env, config);
  if (payload.action === "closed") return gate.closed(payload.issue.node_id);
  if (payload.action === "reopened") return gate.reopened(payload.issue.node_id);
  return gate.touched(payload.issue.node_id);
}
