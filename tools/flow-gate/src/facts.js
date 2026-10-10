// タスクの事実を読む（src/decide.js: decide が受ける形）。置き場の issue とコードのリポジトリの作業ブランチの PR を GraphQL の1回で、
// 担当の実行を REST で読む。App はどちらのリポジトリにも入っている（tasks#797）。ボードの一覧（src/dispatch.js）も同じ読み方を使う。
import { checkQuestion, latestQuestion, norm, remaining } from "./questions.js";

// ボードの欄（ステータス・優先度・着手可能日時）の読み方。欄の名前は設定が持つ。
export const fieldsOf = ({ fields: f }) => `status:fieldValueByName(name:"${f.status}"){...on ProjectV2ItemFieldSingleSelectValue{name}}
 priority:fieldValueByName(name:"${f.priority}"){...on ProjectV2ItemFieldSingleSelectValue{name}} start:fieldValueByName(name:"${f.start}"){...on ProjectV2ItemFieldTextValue{text}}`;
// 着手可能日時は「YYYY-MM-DD」か「YYYY-MM-DD HH:MM」で、日本時間として読む。読めない値は、待つと決めた意図を守ってまだ先と読む。
const jst = (text) => (text ? new Date(`${text.trim().replace(" ", "T")}${text.includes(":") ? "" : "T00:00"}:00+09:00`) : null);
// ボードの項目から、ボードの世界・欄・前提と日時の待ちを組む（1件を決め直すときも、振り出しの一覧も同じ）。
export function taskOf(config, issue, items, now = new Date()) {
  const [world, item] = Object.entries(config.boards).map(([w, n]) => [w, items.find((i) => i.project.number === n)]).find(([, i]) => i) ?? [null, null];
  return { board: world, item: item?.id ?? null, status: item?.status?.name ?? null, priority: item?.priority?.name ?? null, type: issue.issueType?.name ?? null,
    open: issue.state === "OPEN", blocked: (issue.blockedBy?.nodes ?? []).some((b) => b.state === "OPEN"), future: Boolean(item?.start?.text) && !(jst(item.start.text) <= now) };
}
// 担当の実行の名前「#<番号> <種類>」（claude-task.yml の run-name）。
export function runOf(title) {
  const [, number, kind] = /^#(\d+) (\S+)/.exec(title ?? "") ?? [];
  return number ? { number: Number(number), kind } : null;
}

// 動いている担当の実行（始まる前の順番待ちを含む）。
export async function readRuns(gh, config) {
  const { workflow_runs: runs } = await gh.rest("GET", `/repos/${config.code}/actions/workflows/${config.workflow}/runs?per_page=50`);
  return runs.filter((r) => r.status !== "completed" && runOf(r.display_title)).map((r) => ({ id: r.id, ...runOf(r.display_title) }));
}

const query = (config) => `query($to:String!,$tn:String!,$n:Int!,$co:String!,$cn:String!,$head:String!){
 t:repository(owner:$to,name:$tn){issue(number:$n){id state stateReason body author{login} issueType{name} assignees(first:10){nodes{login}}
  blockedBy(first:20){nodes{state}} comments(last:40){nodes{body}} projectItems(first:5){nodes{id project{number} ${fieldsOf(config)}}}
  parent{projectItems(first:5){nodes{project{number} ${fieldsOf(config)}}}}
  timelineItems(first:50,itemTypes:[ISSUE_TYPE_CHANGED_EVENT]){nodes{...on IssueTypeChangedEvent{prevIssueType{name} issueType{name}}}}
  closed:timelineItems(last:1,itemTypes:[CLOSED_EVENT]){nodes{...on ClosedEvent{actor{login}}}}}}
 c:repository(owner:$co,name:$cn){pullRequests(headRefName:$head,first:5,orderBy:{field:CREATED_AT,direction:DESC}){nodes{
  id state isDraft merged mergeCommit{statusCheckRollup{state}} commits(last:2){nodes{commit{oid committedDate statusCheckRollup{state}}}}
  timelineItems(last:1,itemTypes:[CONVERT_TO_DRAFT_EVENT]){nodes{...on ConvertToDraftEvent{createdAt}}}}}}}`;
const ROLLUP = { SUCCESS: "SUCCESS", FAILURE: "FAILURE", ERROR: "FAILURE", PENDING: "PENDING", EXPECTED: "PENDING" };

// 変異テストの生き残り（ファイルと文。行の位置は変わるので使わない）。コミットごとに変わらないので覚えておく。
const seen = new Map();
function survivors(gh, config, sha) {
  if (!seen.has(sha)) seen.set(sha, (async () => {
    const { check_runs: [run] } = await gh.rest("GET", `/repos/${config.code}/commits/${sha}/check-runs?check_name=${config.mutationCheck}`);
    const notes = run ? await gh.rest("GET", `/repos/${config.code}/check-runs/${run.id}/annotations?per_page=100`) : [];
    return notes.filter((a) => a.title === "テストが気づかない書き換え").map((a) => `${a.path}: ${a.message}`);
  })());
  return seen.get(sha);
}

// runs は担当の実行の一覧か、その Promise（読む要求を並べるため）。
export async function readFacts(gh, config, number, runs) {
  const [to, tn] = config.tasks.split("/");
  const [co, cn] = config.code.split("/");
  const [{ t: { issue: i }, c }, all] = await Promise.all([gh.gql(query(config), { to, tn, n: number, co, cn, head: `${config.branchPrefix}${number}` }), runs]);
  const held = all.filter((r) => r.number === number);
  const open = c.pullRequests.nodes.find((p) => p.state === "OPEN");
  const [prev, head] = open?.commits.nodes.length === 2 ? open.commits.nodes : [null, open?.commits.nodes.at(-1)];
  const checks = ROLLUP[head?.commit.statusCheckRollup?.state] ?? null;
  // 生き残りは、持たれていない下書きの PR の CI が通ったときだけ要る（決め3）。前のコミットに無かったものが新しい生き残り。
  const [before, now] = !held.length && open?.isDraft && checks === "SUCCESS"
    ? await Promise.all([prev ? survivors(gh, config, prev.commit.oid) : [], survivors(gh, config, head.commit.oid)]) : [[], []];
  const drafted = open?.timelineItems.nodes[0]?.createdAt;
  const changes = i.timelineItems.nodes;
  const merged = c.pullRequests.nodes.find((p) => p.merged); // 新しいものから並ぶ
  const last = i.comments.nodes.at(-1)?.body;
  return { ...taskOf(config, i, i.projectItems.nodes), number, id: i.id, closedAs: i.stateReason, closedBy: i.closed.nodes[0]?.actor?.login ?? null, author: i.author?.login, body: i.body ?? "",
    remaining: remaining(i.body), assigned: i.assignees.nodes.some((a) => a.login === config.user), question: latestQuestion(i.comments.nodes.map((n) => n.body), config.questionTemplate),
    runs: held, parent: Boolean(i.parent), parentPriority: i.parent ? taskOf(config, {}, i.parent.projectItems.nodes).priority : null,
    // 種類の移り変わり（最初の種類から順に）。変わっていなければ今の種類だけ。
    types: changes.length ? [changes[0].prevIssueType?.name ?? null, ...changes.map((e) => e.issueType?.name ?? null)] : [i.issueType?.name ?? null],
    merged: Boolean(merged), mergeChecks: ROLLUP[merged?.mergeCommit?.statusCheckRollup?.state] ?? null,
    badQuestion: last && /^## 問い/.test(norm(last)) ? checkQuestion(config.questionTemplate, last) : [],
    pr: open && { id: open.id, draft: open.isDraft, checks, newSurvivors: now.some((s) => !before.includes(s)), backToDraft: Boolean(drafted && head && drafted > head.commit.committedDate) } };
}
