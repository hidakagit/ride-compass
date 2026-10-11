// ゲート: 出来事を受け、どのタスクかを決め、事実を全部読み（src/facts.js）、あるべき姿を決め（src/decide.js）、今と違う所だけを書く。
// ステータスと、変わってはいけない値（種類・担当者・本文のボタンと条件・ボード・優先度）を書くのはゲートだけ。
import { decide, DISPATCH } from "./decide.js";
import { mismatched } from "./dispatch.js";
import { readFacts, readRuns, runOf } from "./facts.js";
import { GitHub } from "./github.js";
import { askText, norm } from "./questions.js";

const boards = new Map();
// ボードの id と単一選択の欄（ボードごとに1回だけ読む）。読めなかったら覚えず、次に読み直す。
export async function board(gh, config, world) {
  const number = config.boards[world];
  if (!boards.has(number)) {
    const read = gh.gql(`query($o:String!,$n:Int!){organization(login:$o){projectV2(number:$n){id fields(first:30){nodes{...on ProjectV2SingleSelectField{id name options{id name}}}}}}}`,
      { o: config.owner, n: number }).then((r) => r.organization.projectV2);
    read.catch(() => boards.delete(number));
    boards.set(number, read);
  }
  return boards.get(number);
}

async function setField(gh, config, world, item, name, option) {
  const p = await board(gh, config, world);
  const field = p.fields.nodes.find((n) => n.name === name);
  const value = field?.options.find((o) => o.name === option);
  if (!value) throw new Error(`${world} のボードの ${name} に「${option}」が無い`);
  await gh.gql(`mutation($p:ID!,$i:ID!,$f:ID!,$v:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$v}}){clientMutationId}}`,
    { p: p.id, i: item, f: field.id, v: value.id });
}

// 1つのタスクを決め直して、今と違う所だけを書く。本文（ボタン）は問いのコメントより先に書く（問いの通知から開いたときにボタンがあるように）。閉じるのは最後。
// moved は、ユーザーがボードでステータスを動かした出来事で決め直すとき（戻したら知らせる）。
export async function settle(gh, config, number, runs, moved = false) {
  const f = { ...(await readFacts(gh, config, number, runs)), moved };
  const d = decide(f, config);
  const issue = `/repos/${config.tasks}/issues/${number}`;
  const patch = { ...(d.open && !f.open ? { state: "open" } : {}), ...(d.type !== f.type ? { type: d.type } : {}), ...(d.body !== norm(f.body) ? { body: d.body } : {}) };
  if (Object.keys(patch).length) await gh.rest("PATCH", issue, patch);
  if (d.ask) await gh.rest("POST", `${issue}/comments`, { body: askText(d.ask, config.questionTemplate) });
  if (d.notice) await gh.rest("POST", `${issue}/comments`, { body: d.notice });
  if (d.ready && f.pr?.draft) await gh.gql(`mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){clientMutationId}}`, { id: f.pr.id });
  await Promise.all(d.cancel.map((id) => gh.rest("POST", `/repos/${config.code}/actions/runs/${id}/cancel`)));
  // ボードへ入っていなければ、決めた世界のボードへ入れる（入口）。
  const item = f.item ?? (await gh.gql(`mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}`,
    { p: (await board(gh, config, d.board)).id, c: f.id })).addProjectV2ItemById.item.id;
  if (d.status !== f.status) await setField(gh, config, d.board, item, config.fields.status, d.status);
  if (d.priority && d.priority !== f.priority) await setField(gh, config, d.board, item, config.fields.priority, d.priority); // 段階は親の優先度を継ぐ
  if (d.assigned !== f.assigned) await gh.rest(d.assigned ? "POST" : "DELETE", `${issue}/assignees`, { assignees: [config.user] });
  if (!d.open && f.open) await gh.rest("PATCH", issue, { state: "closed", state_reason: d.closeAs.toLowerCase() });
  return { number, before: f.status, ...d };
}

// 事実を変える出来事だけを受ける。ゲート自身と Claude の本文の書き換えは受けない（問いの道具はボタンを書いてから問いを書く）。
const ACTIONS = { issues: ["opened", "closed", "reopened", "typed", "untyped", "labeled", "unlabeled", "edited"], issue_comment: ["created"],
  pull_request: ["opened", "closed", "reopened", "synchronize", "converted_to_draft", "ready_for_review"] };

// 出来事から、決め直すタスクの番号と、担当の枠が空いたか（free）を決める。
export async function route(gh, config, name, p) {
  if (ACTIONS[name] && !ACTIONS[name].includes(p.action)) return { numbers: [] };
  const fromCode = p.repository?.full_name === config.code;
  // 前提が閉じたら、その後ろで待っていたタスクも決め直す（閉じたのがゲート自身でも）。
  if (name === "issues" && p.action === "closed" && !fromCode) {
    const [o, r] = config.tasks.split("/");
    const after = (await gh.gql(`query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){issue(number:$n){blocking(first:20){nodes{number state}}}}}`,
      { o, r, n: p.issue.number })).repository.issue.blocking.nodes.filter((b) => b.state === "OPEN").map((b) => b.number);
    return { numbers: p.sender?.login === config.gateBot ? after : [p.issue.number, ...after] };
  }
  if (p.sender?.login === config.gateBot && name !== "workflow_run") return { numbers: [] };
  if (name === "issues" && p.action === "edited" && p.sender?.login === config.claude) return { numbers: [] };
  const branch = (ref) => (ref?.startsWith(config.branchPrefix) ? [Number(ref.slice(config.branchPrefix.length))] : []);
  if (["issues", "issue_comment"].includes(name) && !fromCode) return { numbers: [p.issue.number] };
  if (name === "pull_request" && fromCode) return { numbers: branch(p.pull_request.head.ref) };
  if (name === "workflow_run" && fromCode) {
    const done = p.action === "completed";
    if (!p.workflow_run.path.endsWith(config.workflow)) return { numbers: done ? branch(p.workflow_run.head_branch) : [] };
    const run = runOf(p.workflow_run.display_title);
    return { numbers: run ? [run.number] : [], free: done };
  }
  if (name === "projects_v2_item" && p.changes?.field_value?.field_name === config.fields.status) {
    const ours = await Promise.all(Object.keys(config.boards).map((w) => board(gh, config, w)));
    if (!ours.some((b) => b.id === p.projects_v2_item.project_node_id)) return { numbers: [] };
    const node = (await gh.gql(`query($id:ID!){node(id:$id){...on Issue{number}}}`, { id: p.projects_v2_item.content_node_id })).node;
    return { numbers: node?.number ? [node.number] : [], moved: p.sender?.login === config.user };
  }
  if (name === "schedule") { // 定時の突き合わせ（src/index.js: scheduled）
    const known = await mismatched(gh, config);
    return { numbers: known.numbers, free: true, known };
  }
  return { numbers: [] };
}

// 盤面に表れないゲートの事実を、Actions のボードの状況の更新に出す（盤面を持つのはゲート）。定時の突き合わせが落ちた（Off track）・
// 振り出しを止めている（At risk。理由といつまで）・保っている（On track）の1行と、突き合わせで決め直したタスク（出来事の取りこぼし）。
// 15分ごとに起きるので、状態か1行が変わったときと、決め直したタスクがあったときだけ足す。
export async function reportHealth(gh, config, { error = null, stopped = null, fixed = [] } = {}) {
  const p = await board(gh, config, "actions");
  const r = await gh.gql(`query($id:ID!){node(id:$id){...on ProjectV2{statusUpdates(first:1,orderBy:{field:CREATED_AT,direction:DESC}){nodes{status body creator{login}}}}}}`, { id: p.id });
  const last = r.node.statusUpdates.nodes[0];
  const [status, head] = error ? ["OFF_TRACK", "ゲートの定時の突き合わせが失敗している（盤面が事実とずれていても直らない）"]
    : stopped ? ["AT_RISK", `振り出しを止めている: ${stopped}`] : ["ON_TRACK", "ゲートは盤面を保っている（定時の突き合わせが通っている）"];
  const same = last ? last.status === status && last.body.split("\n")[0] === head : status === "ON_TRACK";
  if (same && !fixed.length) return;
  const body = [head, error && `誤り: ${String(error.message ?? error).split("\n")[0]}`,
    fixed.length && `定時の突き合わせで決め直したタスク（出来事の取りこぼし）: ${fixed.map((n) => `#${n}`).join("・")}`].filter(Boolean).join("\n\n");
  await gh.gql(`mutation($p:ID!,$s:ProjectV2StatusUpdateStatus!,$b:String!){createProjectV2StatusUpdate(input:{projectId:$p,status:$s,body:$b}){clientMutationId}}`,
    { p: p.id, s: status, b: body });
}

// 担当の枠が空いたか、決め直したタスクが振り出せるステータスへ来たら、振り出しの窓口（src/dispatcher.js: Dispatcher）に頼む。
// 出来事ごとの処理は同時に動くので、振り出しは1つの窓口で順に扱う（同じタスクを2度つかまない）。
export async function handleEvent(env, config, name, payload) {
  const gh = await GitHub.app(env, config.installation);
  const { numbers, free, moved, known } = await route(gh, config, name, payload);
  if (!numbers.length && !free) return { fixed: [], stopped: null };
  const runs = known ? Promise.resolve(known.runs) : readRuns(gh, config);
  const settled = await Promise.all(numbers.map((n) => settle(gh, config, n, runs, moved)));
  // 定時の突き合わせは、読み済みのボードのタスクへ決め直した結果を重ねて振り出す（読み直さない）。
  const now = new Map(settled.map((d) => [d.number, d]));
  const tasks = known?.tasks.filter((t) => !now.get(t.number) || now.get(t.number).open).map((t) => (now.has(t.number) ? { ...t, status: now.get(t.number).status } : t));
  const sent = free || settled.some((d) => d.status !== d.before && DISPATCH[d.status]) ? await env.DISPATCHER.get(env.DISPATCHER.idFromName("one")).dispatch(config, tasks) : { stopped: null };
  // 突き合わせで決め直したタスクのうち、出来事を取りこぼしていたもの（CI待ちは、マージのあとの master の CI の終わりを出来事で受けないので、
  // 定時の突き合わせで進むのが普通の流れ。数えない）と、振り出しを止めている理由。定時の起動が状況の更新に出す。
  return { fixed: settled.filter((d) => d.status !== d.before && d.before !== "CI待ち").map((d) => d.number), stopped: sent.stopped };
}
