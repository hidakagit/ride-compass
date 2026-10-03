// Project の「状況の更新」（Status updates）。振り出しの見回り（bin/dispatch.js）が全体の様子を書く。最新の1件が Project の
// 見出しと一覧に出る。
import { Mutations } from "./github.js";

// 見回りの書いた更新の本文は、この行で始まる（ほかの者の更新と見分ける）。
const HEAD = "振り出しの見回り";

// 最新の更新が見回りのもので、状態も本文も同じなら何もしない。状態が同じなら本文だけ書き換え、状態が変わったか最新が
// 見回りのものでなければ新しく足す（3分ごとの見回りで履歴を増やさず、履歴には状態の移り変わりだけが残る）。
// 書いたら "created"・"updated"、書かなければ null を返す。
export async function putStatus(gh, config, { status, body }) {
  if (!body.startsWith(HEAD)) throw new Error(`見回りの状況の更新は「${HEAD}」で始める`);
  const d = await gh.gql(
    `query Updates($o: String!, $n: Int!, $k: Int!) { organization(login: $o) { projectV2(number: $n) { id
      statusUpdates(first: $k, orderBy: { field: CREATED_AT, direction: DESC }) { nodes { id status body creator { login } } } } } }`,
    { o: config.project.owner, n: config.project.number, k: 1 },
  );
  const p = d.organization.projectV2;
  const latest = p.statusUpdates.nodes[0];
  const ours = latest?.creator?.login === config.claude && latest.body?.startsWith(HEAD) ? latest : null;
  if (ours?.status === status && ours.body === body) return null;
  const m = new Mutations();
  if (ours?.status === status) m.add("updateProjectV2StatusUpdate", { statusUpdateId: ours.id, status, body });
  else m.add("createProjectV2StatusUpdate", { projectId: p.id, status, body });
  await m.send(gh);
  return ours?.status === status ? "updated" : "created";
}
