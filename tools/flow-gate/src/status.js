// Project の「状況の更新」（Status updates）。ゲート（index.js）が出来事の処理の失敗を書く。最新の1件が Project の見出しと一覧に出る。
import { GitHub, Mutations } from "./github.js";

const AT_RISK = "AT_RISK";

// 新しいものから k 件。by は書いた者のログイン名。
async function readUpdates(gh, config, k = 20) {
  const d = await gh.gql(
    `query Updates($o: String!, $n: Int!, $k: Int!) { organization(login: $o) { projectV2(number: $n) { id
      statusUpdates(first: $k, orderBy: { field: CREATED_AT, direction: DESC }) { nodes { id status body createdAt updatedAt creator { login } } } } } }`,
    { o: config.project.owner, n: config.project.number, k },
  );
  const p = d.organization.projectV2;
  return { projectId: p.id, updates: p.statusUpdates.nodes.map(({ creator, ...u }) => ({ ...u, by: creator?.login ?? null })) };
}

// target に更新を渡せばその本文と状態を書き換え、無ければ新しく足す。
function putUpdate(gh, projectId, target, status, body) {
  const m = new Mutations();
  if (target) m.add("updateProjectV2StatusUpdate", { statusUpdateId: target.id, status, body });
  else m.add("createProjectV2StatusUpdate", { projectId, status, body });
  return m.send(gh);
}

const clock = (date) =>
  new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
    .format(date)
    .replace(/\//g, "-");

const FAILURE = "ゲートが出来事の処理に失敗しました（新しいものが上）。";
const FAILURE_LINES = 20;

// ゲートの処理の失敗を At risk で知らせる。最新の更新もゲートの失敗なら、新しく足さずに1行足す（鍵が切れたときなど、
// 出来事ごとに失敗しても履歴を増やさないため）。
export async function reportFailure(env, config, name, payload, error) {
  const gh = await GitHub.asApp(env, config.installation);
  const { projectId, updates } = await readUpdates(gh, config, 1);
  const target = [
    payload.issue && `#${payload.issue.number}`,
    payload.pull_request && `Pull Request ${payload.pull_request.head?.ref ?? ""}`.trim(),
    payload.projects_v2_item && `Project の件 ${payload.projects_v2_item.content_node_id}`,
  ].find(Boolean);
  const line = `- ${clock(new Date())} ${name}${payload.action ? `.${payload.action}` : ""}${target ? ` ${target}` : ""}: ${String(error?.message ?? error).slice(0, 300)}`;
  const latest = updates[0];
  const same = latest?.status === AT_RISK && latest.body?.startsWith(FAILURE) ? latest : null;
  const lines = [line, ...(same ? same.body.slice(FAILURE.length).trim().split("\n") : [])].slice(0, FAILURE_LINES);
  await putUpdate(gh, projectId, same, AT_RISK, `${FAILURE}\n\n${lines.join("\n")}`);
}
