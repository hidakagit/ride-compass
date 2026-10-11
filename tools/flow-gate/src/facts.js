// タスクの事実を読む（src/decide.js: decide が受ける形）。置き場の issue とコードのリポジトリの作業ブランチの PR を GraphQL の1回で読み、
// 担当が付いているかは見回りの記録（src/patrol.js: Patrol）から受ける。見回りのボードの一覧も同じ読み方を使う。
import { checkQuestion, isQuestion, latestQuestion, norm, remaining } from "./questions.js";

// ボードの欄（ステータス・優先度・着手可能日時）の読み方。欄の名前は設定が持つ。
export const fieldsOf = ({ fields: f }) => `status:fieldValueByName(name:"${f.status}"){...on ProjectV2ItemFieldSingleSelectValue{name}}
 priority:fieldValueByName(name:"${f.priority}"){...on ProjectV2ItemFieldSingleSelectValue{name}} start:fieldValueByName(name:"${f.start}"){...on ProjectV2ItemFieldTextValue{text}}`;
// 着手可能日時は「YYYY-MM-DD」か「YYYY-MM-DD HH:MM」（日本時間）だけを受ける。形の合わない値は受け入れず（badStart はその値。ゲートが知らせる）、
// 待つと決めた意図を守ってまだ先と読む。
const START_FORM = /^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$/;
const jst = (text) => (START_FORM.test(text) ? new Date(`${text.replace(" ", "T")}${text.includes(":") ? "" : "T00:00"}:00+09:00`) : null);
// issue が入っているゲートのボードの世界と項目（設定の順に探す）。
const itemOf = (config, items) => Object.entries(config.boards).map(([world, n]) => ({ world, item: items.find((i) => i.project.number === n) })).find((x) => x.item) ?? {};
// ボードの項目から、ボードの世界・欄・前提と日時の待ちを組む（1件を決め直すときも、振り出しの一覧も同じ）。
export function taskOf(config, issue, items, now = new Date()) {
  const { world, item } = itemOf(config, items);
  const text = item?.start?.text?.trim();
  const start = jst(text);
  return { board: world, item: item?.id, status: item?.status?.name, priority: item?.priority?.name, type: issue.issueType?.name ?? null,
    open: issue.state === "OPEN", blocked: issue.blockedBy.nodes.some((b) => b.state === "OPEN"), future: Boolean(text) && (!start || start > now), badStart: text && !start ? text : null };
}
export const jstText = (ms) => new Date(ms + 9 * 3600e3).toISOString().slice(0, 16).replace("T", " "); // 日本時間の「YYYY-MM-DD HH:MM」
// 担当の実行の名前「#<番号> <種類> <振り出しの識別子>」（claude-task.yml の run-name。手で起こした実行は識別子が無い）。
export function runOf(title) {
  const [, number, kind, key] = /^#(\d+) (\S+)(?: (\S+))?/.exec(title ?? "") ?? [];
  return number ? { number: Number(number), kind, key } : null;
}

const query = (config) => `query($to:String!,$tn:String!,$n:Int!,$co:String!,$cn:String!,$head:String!){
 t:repository(owner:$to,name:$tn){issue(number:$n){id state stateReason body author{login} issueType{name} assignees(first:10){nodes{login}}
  blockedBy(first:20){nodes{state}} comments(last:40){nodes{body}} projectItems(first:5){nodes{id project{number} ${fieldsOf(config)}}}
  parent{projectItems(first:5){nodes{project{number} ${fieldsOf(config)}}}}
  timelineItems(first:50,itemTypes:[ISSUE_TYPE_CHANGED_EVENT]){nodes{...on IssueTypeChangedEvent{prevIssueType{name} issueType{name}}}}}}
 c:repository(owner:$co,name:$cn){pullRequests(headRefName:$head,first:5,orderBy:{field:CREATED_AT,direction:DESC}){nodes{
  id state isDraft merged mergeCommit{statusCheckRollup{state}} commits(last:1){nodes{commit{oid committedDate statusCheckRollup{state}}}}
  timelineItems(last:1,itemTypes:[CONVERT_TO_DRAFT_EVENT]){nodes{...on ConvertToDraftEvent{createdAt}}}}}}}`;
const ROLLUP = { SUCCESS: "SUCCESS", FAILURE: "FAILURE", ERROR: "FAILURE", PENDING: "PENDING", EXPECTED: "PENDING" };

// 変異テストの生き残りの数と、その結果が出た時刻。
async function survivors(gh, config, sha) {
  const { check_runs: [run] } = await gh.rest("GET", `/repos/${config.code}/commits/${sha}/check-runs?check_name=${config.mutationCheck}`);
  const notes = run ? await gh.rest("GET", `/repos/${config.code}/check-runs/${run.id}/annotations?per_page=100`) : [];
  return { count: notes.filter((a) => a.title === "テストが気づかない書き換え").length, at: Date.parse(run?.completed_at) };
}

// record は見回りの担当の記録（終わった実行の印を含む。src/patrol.js: Patrol）。
export async function readFacts(gh, config, number, record) {
  const [to, tn] = config.tasks.split("/");
  const [co, cn] = config.code.split("/");
  const { t: { issue: i }, c } = await gh.gql(query(config), { to, tn, n: number, co, cn, head: `${config.branchPrefix}${number}` });
  const mine = record.filter((r) => r.number === number);
  const runs = mine.filter((r) => r.state !== "completed");
  const made = Math.max(0, ...mine.filter((r) => r.state === "completed" && r.kind === "作る").map((r) => r.at));
  const open = c.pullRequests.nodes.find((p) => p.state === "OPEN");
  const head = open?.commits.nodes.at(-1);
  const checks = ROLLUP[head?.commit.statusCheckRollup?.state];
  // 生き残りは、持たれていない PR の CI が通ったときだけ要る。作る担当がその結果のあとに持っていなければ新しい。
  const mutants = !runs.length && open && checks === "SUCCESS" ? await survivors(gh, config, head.commit.oid) : { count: 0 };
  const drafted = open?.timelineItems.nodes[0]?.createdAt;
  const merged = c.pullRequests.nodes.find((p) => p.merged); // 新しいものから並ぶ
  const comments = i.comments.nodes.map((n) => norm(n.body)); // 最近のコメント（同じ知らせを重ねないためにも読む）
  const last = comments.at(-1);
  return { ...taskOf(config, i, i.projectItems.nodes), number, id: i.id, closedAs: i.stateReason, author: i.author?.login, body: i.body,
    remaining: remaining(i.body), assignees: i.assignees.nodes.map((a) => a.login), question: latestQuestion(comments, config.questionTemplate),
    runs, parent: Boolean(i.parent), parentPriority: i.parent && itemOf(config, i.parent.projectItems.nodes).item?.priority?.name,
    types: i.timelineItems.nodes.map((e) => e.prevIssueType?.name ?? null), // 今より前の種類（古い順）
    merged: Boolean(merged), mergeChecks: ROLLUP[merged?.mergeCommit?.statusCheckRollup?.state],
    badQuestion: last && isQuestion(last) ? checkQuestion(config.questionTemplate, last) : [], comments,
    pr: open && { id: open.id, draft: open.isDraft, checks, newSurvivors: mutants.count > 0 && !(made > mutants.at), backToDraft: Boolean(drafted && drafted > head.commit.committedDate) } };
}
