// Project の「状況の更新」（Status updates）。今の状態は最新の1件が持ち、Project の見出しと一覧に出る。
// 司令塔（bin/status.js）が様子を、ゲート（index.js）が出来事の処理の失敗を、見張り（bin/watch.js）が司令塔の止まりを書く。
import { GitHub, Mutations } from "./github.js";
import { claude } from "./rules.js";

export const ON_TRACK = "ON_TRACK";
export const AT_RISK = "AT_RISK";
export const OFF_TRACK = "OFF_TRACK";

// 新しいものから k 件。by は書いた者のログイン名。
export async function readUpdates(gh, config, k = 20) {
  const d = await gh.gql(
    `query Updates($o: String!, $n: Int!, $k: Int!) { organization(login: $o) { projectV2(number: $n) { id
      statusUpdates(first: $k, orderBy: { field: CREATED_AT, direction: DESC }) { nodes { id status body createdAt updatedAt creator { login } } } } } }`,
    { o: config.project.owner, n: config.project.number, k },
  );
  const p = d.organization.projectV2;
  return { projectId: p.id, updates: p.statusUpdates.nodes.map(({ creator, ...u }) => ({ ...u, by: creator?.login ?? null })) };
}

// target に更新を渡せばその本文と状態を書き換え、無ければ新しく足す。
export function putUpdate(gh, projectId, target, status, body) {
  const m = new Mutations();
  if (target) m.add("updateProjectV2StatusUpdate", { statusUpdateId: target.id, status, body });
  else m.add("createProjectV2StatusUpdate", { projectId, status, body });
  return m.send(gh);
}

// 司令塔の最後の更新。司令塔は On track・At risk だけを書き、Claude の名義の Off track は見張りのもの。
export const coordinatorUpdate = (config, updates) => updates.find((u) => u.by === claude(config) && u.status !== OFF_TRACK);

// 司令塔の最後の更新が coordinator.staleMinutes より古ければ、Off track を足す（司令塔が起きなくなると、誰も
// 書かないので見出しが最後の On track のまま残るため）。最新が見張りの Off track なら、もう知らせてあるので足さない。
// 司令塔は次の1回で新しい更新を足し、見出しを戻す。返すのはしたことの1行。
export async function watchCoordinator(gh, config, now = Date.now()) {
  const { projectId, updates } = await readUpdates(gh, config);
  const last = coordinatorUpdate(config, updates);
  if (!last) return "司令塔の更新がまだ無い";
  const minutes = Math.floor((now - Date.parse(last.updatedAt)) / 60000);
  const since = `司令塔が最後に起きた時刻: ${clock(new Date(last.updatedAt))}（${Math.floor(minutes / 60)}時間${minutes % 60}分前）`;
  if (minutes <= config.coordinator.staleMinutes) return `止まっていない。${since}`;
  if (updates[0].by === claude(config) && updates[0].status === OFF_TRACK) return `もう Off track を出してある。${since}`;
  const body = [
    `**司令塔が止まっている**（${config.coordinator.staleMinutes / 60}時間を超えて、状況の更新を書いていない）`,
    "",
    `- ${since}（日本時間）`,
    `- 見張りが見た時刻: ${clock(new Date(now))}`,
    "- 考えられること: PC が寝ている・アプリが閉じている・許可の確認で止まっている。司令塔が次に起きると、この見出しは戻る",
  ].join("\n");
  await putUpdate(gh, projectId, null, OFF_TRACK, body);
  return `Off track を足した。${since}`;
}

export const clock = (date) =>
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
