// ゲート: 出来事を受け、どのタスクかを決め、事実を全部読み（src/facts.js）、あるべき姿を決め（src/decide.js）、今と違う所だけを書く。
// ステータスと、変わってはいけない値（種類・担当者・本文のボタンと条件・ボード・優先度）を書くのはゲートだけ。
import { decide, DISPATCH } from "./decide.js";
import { dispatch, mismatched } from "./dispatch.js";
import { readFacts, readRuns, runOf } from "./facts.js";
import { GitHub } from "./github.js";
import { askText, norm } from "./questions.js";

const boards = new Map();
// ボードの id と単一選択の欄（ボードごとに1回だけ読む）。
export async function board(gh, config, world) {
  const number = config.boards[world];
  if (!boards.has(number))
    boards.set(number, gh.gql(`query($o:String!,$n:Int!){organization(login:$o){projectV2(number:$n){id fields(first:30){nodes{...on ProjectV2SingleSelectField{id name options{id name}}}}}}}`,
      { o: config.owner, n: number }).then((r) => r.organization.projectV2));
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

// 1つのタスクを決め直して、今と違う所だけを書く。本文（ボタン）は問いのコメントより先に書く（要件 R13）。閉じるのは最後。
export async function settle(gh, config, number, runs) {
  const f = await readFacts(gh, config, number, runs);
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
  return { before: f.status, ...d };
}

// 事実を変える出来事だけを受ける。ゲート自身と Claude の本文の書き換えは受けない（問いの道具はボタンを書いてから問いを書く）。
const ACTIONS = { issues: ["opened", "closed", "reopened", "typed", "untyped", "labeled", "unlabeled", "edited"], issue_comment: ["created"],
  pull_request: ["opened", "closed", "reopened", "synchronize", "converted_to_draft", "ready_for_review"] };

// 出来事から、決め直すタスクの番号と、担当の枠が空いたか（free）を決める。
export async function route(gh, config, name, p) {
  if (ACTIONS[name] && !ACTIONS[name].includes(p.action)) return { numbers: [] };
  if (p.sender?.login === config.gateBot && name !== "workflow_run") return { numbers: [] };
  if (name === "issues" && p.action === "edited" && p.sender?.login === config.claude) return { numbers: [] };
  const fromCode = p.repository?.full_name === config.code;
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
    return { numbers: node?.number ? [node.number] : [] };
  }
  if (name === "schedule") return { numbers: await mismatched(gh, config), free: true }; // 定時の突き合わせ（src/index.js: scheduled）
  return { numbers: [] };
}

// 担当の枠が空いたか、決め直したタスクが振り出せるステータスへ来たら、振り出す。
export async function handleEvent(env, config, name, payload) {
  const gh = await GitHub.app(env, config.installation);
  const { numbers, free } = await route(gh, config, name, payload);
  if (!numbers.length && !free) return;
  const runs = readRuns(gh, config);
  const settled = await Promise.all(numbers.map((n) => settle(gh, config, n, runs)));
  if (free || settled.some((d) => d.status !== d.before && DISPATCH[d.status])) await dispatch(gh, config, await runs);
}
