// ゲート: GitHub の出来事から決め直すタスクを決め、事実を全部読み（src/facts.js）、あるべき姿を決め（src/decide.js）、今と違う所だけを書く。
// ステータスと、変わってはいけない値（種類・担当者・本文のボタンと条件・ボード・優先度）を書くのはゲートだけ。
import { decide } from "./decide.js";
import { readFacts } from "./facts.js";
import { askText, bodyRest, norm } from "./questions.js";

// ボードの id と単一選択の欄。
const board = (gh, config, world) => gh.gql(`query($o:String!,$n:Int!){organization(login:$o){projectV2(number:$n){id
  fields(first:30){nodes{...on ProjectV2SingleSelectField{id name options{id name}}}}}}}`, { o: config.owner, n: config.boards[world] }).then((r) => r.organization.projectV2);

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
export async function settle(gh, config, number, record, moved = false) {
  const f = { ...(await readFacts(gh, config, number, record)), moved };
  const d = decide(f, config);
  const issue = `/repos/${config.tasks}/issues/${number}`;
  const patch = { ...(d.open && !f.open ? { state: "open" } : {}), ...(d.type !== f.type ? { type: d.type } : {}), ...(d.body !== norm(f.body) ? { body: d.body } : {}),
    ...(String(d.assignees) !== String(f.assignees) ? { assignees: d.assignees } : {}) };
  if (Object.keys(patch).length) await gh.rest("PATCH", issue, patch);
  if (d.ask) await gh.rest("POST", `${issue}/comments`, { body: askText(d.ask, config.questionTemplate) });
  if (d.notice) await gh.rest("POST", `${issue}/comments`, { body: d.notice });
  if (d.ready) await gh.gql(`mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){clientMutationId}}`, { id: f.pr.id });
  await Promise.all(d.cancel.map((id) => gh.rest("POST", `/repos/${config.code}/actions/runs/${id}/cancel`)));
  // ボードへ入っていなければ、決めた世界のボードへ入れる（入口）。
  const item = f.item ?? (await gh.gql(`mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}`,
    { p: (await board(gh, config, d.board)).id, c: f.id })).addProjectV2ItemById.item.id;
  if (d.status !== f.status) await setField(gh, config, d.board, item, config.fields.status, d.status);
  if (d.priority && d.priority !== f.priority) await setField(gh, config, d.board, item, config.fields.priority, d.priority); // 段階は親の優先度を継ぐ
  if (!d.open && f.open) await gh.rest("PATCH", issue, { state: "closed", state_reason: d.closeAs.toLowerCase() });
  return { ...f, ...d };
}

// 事実を変える出来事だけを、決まった置き場から受ける。ゲート自身の書き込みのこだまは受けない（前提が閉じたときの後ろのタスクは除く）。
const ACTIONS = { issues: ["opened", "closed", "reopened", "typed", "untyped", "labeled", "unlabeled", "edited"], issue_comment: ["created"],
  pull_request: ["opened", "closed", "reopened", "synchronize", "converted_to_draft", "ready_for_review"], workflow_run: ["requested", "in_progress", "completed"], projects_v2_item: ["edited"] };
const REPO = { issues: "tasks", issue_comment: "tasks", pull_request: "code", workflow_run: "code" };
const OWN = ["workflow_run", "issues closed"]; // ゲート自身の出来事でも受けるもの（起こした担当の実行・閉じたタスクの後ろ）
export const ignored = (config, name, p) => !ACTIONS[name]?.includes(p.action) || (REPO[name] && p.repository?.full_name !== config[REPO[name]])
  || (p.sender?.login === config.gateBot && !OWN.includes(name) && !OWN.includes(`${name} ${p.action}`));
const branch = (config, ref) => (ref?.startsWith(config.branchPrefix) ? [Number(ref.slice(config.branchPrefix.length))] : []);

const ROUTES = {
  async issues(gh, config, p) {
    // 回答のボタンだけを書き足した本文の書き換えは受けない（問う者はボタンを書いてから問いを書くので、ここで決め直すとボタンを消す）。
    const buttonOnly = p.action === "edited" && p.changes?.body && bodyRest(p.changes.body.from) === bodyRest(p.issue.body);
    if (p.action !== "closed") return buttonOnly ? [] : [p.issue.number];
    // 前提が閉じたら、その後ろで待っていたタスクも決め直す（閉じたのがゲート自身でも）。
    const [o, r] = config.tasks.split("/");
    const after = (await gh.gql(`query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){issue(number:$n){blocking(first:20){nodes{number state}}}}}`,
      { o, r, n: p.issue.number })).repository.issue.blocking.nodes.filter((x) => x.state === "OPEN").map((x) => x.number);
    return p.sender?.login === config.gateBot ? after : [p.issue.number, ...after];
  },
  issue_comment: (gh, config, p) => [p.issue.number],
  pull_request: (gh, config, p) => branch(config, p.pull_request.head.ref),
  // CI の終わり。マージのコミットの CI は、そのコミットの PR の作業ブランチのタスク。
  async workflow_run(gh, config, p) {
    const w = p.workflow_run;
    if (p.action !== "completed") return [];
    const pulls = w.head_branch === config.base ? await gh.rest("GET", `/repos/${config.code}/commits/${w.head_sha}/pulls`) : [];
    return [w.head_branch, ...pulls.map((pr) => pr.head.ref)].flatMap((ref) => branch(config, ref));
  },
  async projects_v2_item(gh, config, p) {
    if (p.changes?.field_value?.field_name !== config.fields.status) return [];
    const ours = await Promise.all(Object.keys(config.boards).map((w) => board(gh, config, w)));
    if (!ours.some((x) => x.id === p.projects_v2_item.project_node_id)) return [];
    const node = (await gh.gql(`query($id:ID!){node(id:$id){...on Issue{number}}}`, { id: p.projects_v2_item.content_node_id })).node;
    return { numbers: node?.number ? [node.number] : [], moved: p.sender?.login === config.user };
  },
};
export async function route(gh, config, name, p) {
  const r = await ROUTES[name](gh, config, p);
  return Array.isArray(r) ? { numbers: r } : r;
}

// 盤面に表れないゲートの事実を、Actions のボードの状況の更新に出す（盤面を持つのはゲート。ユーザーの決定）。諦めた出来事がある（Off track。
// その出来事での決め直しが抜けている）・振り出しを止めている（At risk。理由といつまで）・保っている（On track）。変わったときだけ足す。
export async function reportHealth(gh, config, { stopped = null, failed = [] } = {}) {
  const p = await board(gh, config, "actions");
  const r = await gh.gql(`query($id:ID!){node(id:$id){...on ProjectV2{statusUpdates(first:1,orderBy:{field:CREATED_AT,direction:DESC}){nodes{status body}}}}}`, { id: p.id });
  const last = r.node.statusUpdates.nodes[0];
  const [status, head] = failed.length ? ["OFF_TRACK", "ゲートがやり直しても処理できなかった出来事がある（その出来事での決め直しが抜けている）"]
    : stopped ? ["AT_RISK", `振り出しを止めている: ${stopped}`] : ["ON_TRACK", "ゲートは出来事を処理できている"];
  if (!failed.length && (last ? last.status === status && last.body.split("\n")[0] === head : status === "ON_TRACK")) return;
  const body = [head, ...failed.map((f) => `- ${f.name}: ${f.error}`)].join("\n");
  await gh.gql(`mutation($p:ID!,$s:ProjectV2StatusUpdateStatus!,$b:String!){createProjectV2StatusUpdate(input:{projectId:$p,status:$s,body:$b}){clientMutationId}}`,
    { p: p.id, s: status, b: body });
}
