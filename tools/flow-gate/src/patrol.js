// 見回り（tasks#788）: 担当が付いているかの記録と振り出し。記録の置き場は src/dispatcher.js: Dispatcher（1つだけ）。
import { fieldsOf, jstText, taskOf } from "./facts.js";

// Actions のボードの開いたタスク（1件を決め直すときと同じ読み方で組む）。
async function items(gh, config) {
  const all = [];
  for (let after = null; ;) {
    const r = await gh.gql(`query($o:String!,$n:Int!,$a:String){organization(login:$o){projectV2(number:$n){items(first:100,after:$a){pageInfo{hasNextPage endCursor}
      nodes{project{number} ${fieldsOf(config)} content{...on Issue{number state issueType{name} labels(first:20){nodes{name}} blockedBy(first:20){nodes{state}}}}}}}}}`,
    { o: config.owner, n: config.boards.actions, a: after });
    const page = r.organization.projectV2.items;
    for (const n of page.nodes) if (n.content?.state === "OPEN")
      all.push({ ...taskOf(config, n.content, [n]), number: n.content.number, urgent: n.content.labels.nodes.some((l) => l.name === config.urgentLabel) });
    if (!page.pageInfo.hasNextPage) return all;
    after = page.pageInfo.endCursor;
  }
}

// 止める操作: 振り出さない理由（無ければ null）。担当のワークフローを無効にしたら止める。最後に終わった担当の実行が
// Claude の利用の上限・認証で止まっていたら（担当のワークフローの段 config.quotaStep が落ちた）、その終わりから pauseMinutes の間止める。
// 理由はボードに表れないので、ボードの状況の更新に出す（src/gate.js: reportHealth）。
async function stopReason(gh, config) {
  const path = `/repos/${config.code}/actions/workflows/${config.workflow}`;
  const [wf, { workflow_runs: [last] }] = await Promise.all([gh.rest("GET", path), gh.rest("GET", `${path}/runs?status=completed&per_page=1`)]);
  if (wf.state !== "active") return "担当のワークフロー（Claude Task）が無効（Actions の画面の Enable workflow で戻す）";
  const until = Date.parse(last?.updated_at) + config.pauseMinutes * 60e3;
  if (last?.conclusion !== "failure" || !(until > Date.now())) return null;
  const { jobs } = await gh.rest("GET", `/repos/${config.code}/actions/runs/${last.id}/jobs`);
  return jobs.some((j) => j.steps?.some((s) => s.name === config.quotaStep && s.conclusion === "failure"))
    ? `担当が Claude の利用の上限か認証で止まったため、${jstText(until)} まで（担当を1件手で起こせば早く戻る）` : null;
}

// 振り出す担当の種類（無ければ null）。前提・未来の着手可能日時・対話作業・担当の付いたものは振り出さない。
const DISPATCH = { 未着手: "作る", 検証待ち: "確かめる" };
const dispatchable = (t, config) => (t.open && !t.runs.length && !t.blocked && !t.future && t.type !== config.dialogType ? (DISPATCH[t.status] ?? null) : null);
const RANK = { dispatched: 0, requested: 1, in_progress: 2, completed: 3 };

// 担当の記録。1件は、振り出し（key。手で起こした実行は実行の id）ごとの { number, kind, key, id, state, at }。
export class Patrol {
  constructor(storage) { this.storage = storage; }
  async all() { return (await this.storage.get("held")) ?? []; }

  // 実行の状態は前にだけ進める。知らせの届く順は決まっていないので、終わった実行の印を1日残し、遅れて届いた始まりの知らせで持ち直さない。
  async observe(run, now = Date.now()) {
    const all = await this.all();
    const same = (h) => (run.key ? h.key === run.key : h.id === run.id);
    const was = all.find(same);
    if (was && RANK[was.state] >= RANK[run.state]) return;
    await this.storage.put("held", [...all.filter((h) => !same(h) && !(h.state === "completed" && now - h.at > 864e5)), { ...was, ...run, at: now }]);
  }

  // 枠に空きがあるときだけボードを読む（定時は、状況の更新に出す止めの理由を空きが無くても調べる）。起こせた分は途中で落ちても記録してから
  // 落とす（受け箱のやり直しで、同じタスクに二度振り出さない）。
  async dispatch(gh, config, settled, kinds, always = false) {
    const held = (await this.all()).filter((h) => h.state !== "completed");
    const wanted = [...new Set([...kinds, ...settled.map((t) => dispatchable(t, config)).filter(Boolean)])];
    const free = Object.fromEntries(wanted.map((kind) => [kind, config.slots[kind] - held.filter((h) => h.kind === kind).length]));
    const room = Object.values(free).some((n) => n > 0);
    const stopped = room || always ? await stopReason(gh, config) : null;
    if (stopped || !room) return { picked: [], stopped };
    const tasks = (await items(gh, config)).map((t) => ({ ...t, runs: held.filter((h) => h.number === t.number) }));
    const rank = (t) => config.priorities.indexOf(t.priority ?? config.unsetPriority);
    const picked = Object.keys(free).flatMap((kind) => tasks.filter((t) => dispatchable(t, config) === kind)
      .sort((a, b) => b.urgent - a.urgent || rank(a) - rank(b) || a.number - b.number)
      .slice(0, Math.max(0, free[kind])).map((t) => ({ number: t.number, kind, key: `${t.number}-${Date.now()}` })));
    const results = await Promise.allSettled(picked.map((p) => gh.rest("POST", `/repos/${config.code}/actions/workflows/${config.workflow}/dispatches`,
      { ref: config.base, inputs: { issue: String(p.number), kind: p.kind, key: p.key } })));
    const sent = picked.filter((_, i) => results[i].status === "fulfilled");
    await this.storage.put("held", [...(await this.all()), ...sent.map((p) => ({ ...p, id: null, state: "dispatched", at: Date.now() }))]);
    const failed = results.find((r) => r.status === "rejected");
    if (failed) throw failed.reason;
    return { picked: sent, stopped: null };
  }
}
