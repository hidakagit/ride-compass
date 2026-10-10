// 振り出しと突き合わせ。どちらもゲートが打つ（振り出しは担当の枠が空いた・振り出せる所へ来た出来事で、突き合わせは定時の頼みで）。
import { dispatchable, HELD } from "./decide.js";
import { fieldsOf, readRuns, taskOf } from "./facts.js";

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

// 止める操作（要件 K6）: 振り出さない理由（無ければ null）。担当のワークフローを無効にしたら止める。最後に終わった担当の実行が
// Claude の利用の上限・認証で止まっていたら（担当のワークフローの段 config.quotaStep が落ちた）、その終わりから pauseMinutes の間止める。
// 理由はボードに表れないので、ボードの状況の更新に出す（src/gate.js: reportHealth）。
async function stopReason(gh, config) {
  const path = `/repos/${config.code}/actions/workflows/${config.workflow}`;
  const [wf, { workflow_runs: [last] }] = await Promise.all([gh.rest("GET", path), gh.rest("GET", `${path}/runs?status=completed&per_page=1`)]);
  if (wf.state !== "active") return "担当のワークフロー（Claude Task）が無効（Actions の画面の Enable workflow で戻す）";
  const until = Date.parse(last?.updated_at) + config.pauseMinutes * 60e3;
  if (last?.conclusion !== "failure" || !(until > Date.now())) return null;
  const { jobs } = await gh.rest("GET", `/repos/${config.code}/actions/runs/${last.id}/jobs`);
  const at = new Date(until + 9 * 3600e3).toISOString().slice(0, 16).replace("T", " "); // 日本時間
  return jobs.some((j) => j.steps?.some((s) => s.name === config.quotaStep && s.conclusion === "failure"))
    ? `担当が Claude の利用の上限か認証で止まったため、${at} まで（担当を1件手で起こせば早く戻る）` : null;
}

// 枠の数まで、急ぎ・優先度・番号の順に振り出す。作る担当の枠 = 進行中、確かめる担当の枠 = 検証中（CI待ちは枠を使わない）。
// 返すのは起こした担当（picked）と、止めているならその理由（stopped）。
export async function dispatch(gh, config, runs) {
  const stopped = await stopReason(gh, config);
  if (stopped) return { picked: [], stopped };
  const tasks = await items(gh, config);
  const rank = (t) => config.priorities.indexOf(t.priority ?? config.unsetPriority);
  const picked = Object.keys(config.slots).flatMap((kind) =>
    tasks.map((t) => ({ ...t, runs: runs.filter((r) => r.number === t.number) })).filter((t) => dispatchable(t, config) === kind)
      .sort((a, b) => b.urgent - a.urgent || rank(a) - rank(b) || a.number - b.number)
      .slice(0, Math.max(0, config.slots[kind] - runs.filter((r) => r.kind === kind).length)).map((t) => ({ issue: String(t.number), kind })));
  await Promise.all(picked.map((inputs) => gh.rest("POST", `/repos/${config.code}/actions/workflows/${config.workflow}/dispatches`, { ref: config.base, inputs })));
  return { picked, stopped: null };
}

// 突き合わせ: ボードのステータスと担当の実行が食い違うタスク（持たれているのに作業のステータスでない・作業のステータスなのに持たれていない）と、
// CI待ちのタスク（CI の終わりの出来事を取りこぼしても拾う）。
export async function mismatched(gh, config) {
  const [tasks, runs] = await Promise.all([items(gh, config), readRuns(gh, config)]);
  const working = Object.values(HELD);
  return tasks.filter((t) => t.status === "CI待ち" || runs.some((r) => r.number === t.number) !== working.includes(t.status)).map((t) => t.number);
}
