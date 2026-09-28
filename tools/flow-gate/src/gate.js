// 遷移の処理。Webhook の出来事も回答フォームの送信も、ここの apply を通って表で照らされる。
import { GitHub, readIssue, readProject } from "./github.js";
import { adoptionQuestion, answers, check, entryFor, parseQuestion, personById, withBanner, withoutBanner } from "./rules.js";

export class Gate {
  static async open(env, config, origin, installationId) {
    const gate = new Gate();
    gate.config = config;
    gate.origin = origin;
    gate.gh = await GitHub.asApp(env, config.repository, installationId);
    gate.project = await readProject(gate.gh, config);
    gate.logins = {};
    return gate;
  }

  read(ref) {
    return readIssue(this.gh, this.config, this.project, ref);
  }

  async login(person) {
    this.logins[person] ??= (await this.gh.rest("GET", `/user/${this.config.people[person].id}`)).login;
    return this.logins[person];
  }

  async setStatus(issue, name) {
    const p = { p: this.project.id, i: issue.item, f: this.project.field };
    if (name === null)
      await this.gh.gql(`mutation Clear($p: ID!, $i: ID!, $f: ID!) { clearProjectV2ItemFieldValue(input: { projectId: $p, itemId: $i, fieldId: $f }) { clientMutationId } }`, p);
    else
      await this.gh.gql(
        `mutation Set($p: ID!, $i: ID!, $f: ID!, $o: String!) { updateProjectV2ItemFieldValue(input: { projectId: $p, itemId: $i, fieldId: $f, value: { singleSelectOptionId: $o } }) { clientMutationId } }`,
        { ...p, o: this.project.options[name] },
      );
  }

  async assign(issue, person) {
    const login = await this.login(person);
    const now = issue.assignees.nodes.map((a) => a.login);
    if (now.length !== 1 || now[0] !== login) await this.patch(issue, { assignees: [login] });
  }

  patch(issue, body) {
    return this.gh.rest("PATCH", `/repos/${this.config.repository}/issues/${issue.number}`, body);
  }

  comment(issue, body) {
    return this.gh.rest("POST", `/repos/${this.config.repository}/issues/${issue.number}/comments`, { body });
  }

  async missingLabels(labels) {
    const missing = [];
    for (const name of labels)
      await this.gh.rest("GET", `/repos/${this.config.repository}/labels/${encodeURIComponent(name)}`).catch(() => missing.push(name));
    return missing;
  }

  // 表で照らし、通れば書く。written はステータスがもう GitHub で変わっていること（ボードの移動）。
  // next を渡さなければ表の既定の割り当てを書く。dryRun は照らすだけで書かない。
  async apply(issue, from, to, { next, labels = [], written = false, dryRun = false } = {}) {
    const verdict = from === to ? { ok: true, rule: null } : check(this.config, from, to, issue.blockedBy.nodes);
    if (!verdict.ok) return verdict;
    const missing = await this.missingLabels(labels);
    if (missing.length) return { ok: false, reason: `ラベル「${missing.join("」「")}」が GitHub にありません。` };
    if (dryRun) return { ok: true };
    if (!written && from !== to) await this.setStatus(issue, to);
    const person = next !== undefined ? next : verdict.rule?.assign;
    if (person) await this.assign(issue, person);
    if (labels.length) await this.gh.rest("POST", `/repos/${this.config.repository}/issues/${issue.number}/labels`, { labels });
    if (to === this.config.done && issue.state === "OPEN") await this.patch(issue, { state: "closed", state_reason: "not_planned" });
    if (from !== to && this.config.ask.statuses.includes(to)) await this.askFor(issue, to);
    issue.status = to;
    await this.syncBanner(issue);
    return { ok: true };
  }

  // 採否待ちへ入ったら採否の問いを決まった中身で書く。それ以外の問いの形が崩れていれば Claude へ戻す。
  async askFor(issue, status) {
    if (status === this.config.adoption.status) {
      const body = adoptionQuestion(this.config);
      const c = await this.comment(issue, body);
      issue.comments.nodes.push({ id: c.node_id, url: c.html_url, body, isMinimized: false, author: { login: this.config.gate.replace(/\[bot\]$/, "") } });
    } else if (!currentQuestion(this.config, issue)?.parsed) {
      await this.comment(issue, "問いの形が崩れています（docs/conventions/flow.md「問い」）。問いを書き直してください。");
      await this.assign(issue, this.config.ask.askers[0]);
    }
  }

  // 回答フォームが要る（採否待ち・回答待ちで、答えの無い問いがある）ときだけ、本文の先頭にリンクを置く。
  async syncBanner(issue) {
    const q = this.config.ask.statuses.includes(issue.status) ? currentQuestion(this.config, issue) : null;
    const open = q?.parsed && !issue.comments.nodes.some((c) => answers(c.body, q.url));
    const url = `${this.origin}/answer?issue=${issue.number}`;
    const body = open ? withBanner(issue.body, issue.status, q.parsed.text, url) : withoutBanner(issue.body);
    if (body !== (issue.body ?? "").replace(/\r\n/g, "\n")) await this.patch(issue, { body });
    issue.body = body;
  }

  // 割り当て・本文・ラベルなどの出来事: リンクの有無だけを今の状態に合わせる（問い直したときにも出す）。
  async touched(nodeId) {
    const issue = await this.read({ nodeId });
    if (issue?.item && !issue.parent) await this.syncBanner(issue);
  }

  async enter(nodeId) {
    const issue = await this.read({ nodeId });
    if (!issue?.item || issue.parent || issue.status) return;
    const entry = entryFor(this.config, issue.author.databaseId);
    await this.setStatus(issue, entry.to);
    await this.assign(issue, entry.assign);
    issue.status = entry.to;
    if (this.config.ask.statuses.includes(entry.to)) await this.askFor(issue, entry.to);
    await this.syncBanner(issue);
  }

  async moved(nodeId, from, to) {
    const issue = await this.read({ nodeId });
    if (!issue?.item || issue.parent || from === to) return;
    const r = await this.apply(issue, from, to, { written: true });
    if (r.ok) return;
    await this.setStatus(issue, from);
    await this.comment(issue, `${r.reason}「${from ?? "（無し）"}」へ戻しました。`);
  }

  async closed(nodeId, reason) {
    const issue = await this.read({ nodeId });
    if (!issue?.item || issue.parent || issue.status === this.config.done) return;
    if (!check(this.config, issue.status, this.config.done).ok) return;
    const stage = reason === "completed" && issue.subIssues.nodes.find((s) => s.state === "OPEN");
    issue.status = stage ? this.config.nextStage.to : this.config.done;
    await this.syncBanner(issue);
    if (!stage) return this.setStatus(issue, this.config.done);
    await this.gh.rest("PATCH", `/repos/${this.config.repository}/issues/${stage.number}`, { state: "closed", state_reason: "completed" });
    await this.patch(issue, { state: "open" });
    await this.setStatus(issue, this.config.nextStage.to);
    await this.assign(issue, this.config.nextStage.assign);
  }

  async reopened(nodeId) {
    const issue = await this.read({ nodeId });
    if (!issue?.item || issue.parent || issue.status !== this.config.done) return;
    const d = await this.gh.gql(
      `query Closed($id: ID!) { node(id: $id) { ... on Issue { timelineItems(last: 1, itemTypes: [CLOSED_EVENT]) { nodes { ... on ClosedEvent { stateReason } } } } } }`,
      { id: nodeId },
    );
    const reason = (d.node.timelineItems.nodes[0]?.stateReason ?? "NOT_PLANNED").toLowerCase();
    await this.patch(issue, { state: "closed", state_reason: reason });
    await this.comment(issue, `「${this.config.done}」からは戻せません（遷移の表に無い）。閉じ直しました。続きは新しい issue にしてください。`);
  }
}

// 今の問い: 問いを書ける者（askers）かゲートが書いた、1行目が「## 問い」のコメントのうち最新の1つ。
export function currentQuestion(config, issue) {
  const gateLogin = config.gate.replace(/\[bot\]$/, "");
  const q = [...issue.comments.nodes]
    .reverse()
    .find(
      (c) =>
        c.body.startsWith("## 問い") &&
        (c.author?.login === gateLogin || config.ask.askers.includes(personById(config, c.author?.databaseId))),
    );
  return q ? { ...q, parsed: parseQuestion(config, q.body) } : null;
}

export async function handleEvent(env, config, origin, name, payload) {
  if (payload.sender?.login === config.gate) return "ゲート自身の出来事";
  const gate = await Gate.open(env, config, origin, payload.installation?.id);
  if (name === "projects_v2_item") {
    const item = payload.projects_v2_item;
    if (item.content_type !== "Issue" || item.project_node_id !== gate.project.id) return "対象外の件";
    if (payload.action === "created") return gate.enter(item.content_node_id);
    const change = payload.changes?.field_value;
    if (payload.action === "edited" && change?.field_node_id === gate.project.field)
      return gate.moved(item.content_node_id, change.from?.name ?? null, change.to?.name ?? null);
  }
  if (name === "issues" && payload.action === "closed") return gate.closed(payload.issue.node_id, payload.issue.state_reason);
  if (name === "issues" && payload.action === "reopened") return gate.reopened(payload.issue.node_id);
  if (name === "issues") return gate.touched(payload.issue.node_id);
  return "対象外の出来事";
}
