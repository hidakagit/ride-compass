// 担当のワークフローの後始末の部品。messages は連携（anthropics/claude-code-action）が書き出す実行のファイル（Agent SDK の
// メッセージの並び）。無ければ null（Claude が起きる前に落ちた）。ステータスは書かない（実行の終わりを受けたゲートが決める）。

const QUOTA = ["rate_limit", "billing_error", "authentication_failed", "oauth_org_not_allowed", "account_on_hold"];

// 振り出しを止める理由（担当の発言の error。無ければ null）: Cancel されずに Claude の利用の上限・認証で止まったときだけ。続けて起こしても
// 同じく止まるので、どちらの担当でも止める。持ち時間を超えた・Cancel された（ジョブの結果 cancelled）は担当の側の止まりなので数えない。
export const pauseOf = (messages, jobStatus) =>
  jobStatus === "cancelled" ? null : ((messages ?? []).find((m) => m?.type === "assistant" && QUOTA.includes(m.error))?.error ?? null);

// issue へ書く「終わり」のコメント。その回にやったことの要約で、後から人と後の担当が読んで確かめる（flow.md「担当」）。担当の最後の
// 発言（担当が書く要約）・後始末がしたこと・判定に断られた操作・実行へのリンクだけを書き、issue と実行のページで読めるもの
// （ステータス・ジョブの結果・時間・手数）は写さない。置き場は非公開なので最後の発言を書いてよい（公開の Actions の記録には出さない）。
// 最後の発言は、GitHub がコメントに許す長さ（API の検証のエラーが出す上限。公式の文書には無い）に収まるように切る。
const LIMIT = 65536;
export function endReport({ kind, url, messages, done }) {
  const result = messages?.findLast((m) => m?.type === "result");
  const said = messages?.filter((m) => m?.type === "assistant").map((m) => (m.message?.content ?? []).filter((c) => c?.type === "text").map((c) => c.text).join("\n").trim()).findLast(Boolean);
  const words = (typeof result?.result === "string" && result.result.trim()) || said || "（無い）";
  const denied = (result?.permission_denials ?? []).map((d) => `${d.tool_name}: ${String(d.tool_input?.command ?? d.tool_input?.file_path ?? d.tool_input?.url ?? "").replace(/\s+/g, " ").slice(0, 100)}`);
  const head = `### ${kind}担当の終わり\n\n要約（担当の最後の発言）:\n\n`;
  const tail = ["", "", "後始末がしたこと:", ...done.map((l) => `- ${l}`),
    ...(denied.length ? ["", "判定に断られた操作:", ...denied.map((d) => `- ${d}`)] : []), "", `実行: ${url}`].join("\n");
  return head + words.split("\n").map((l) => `> ${l}`).join("\n").slice(0, LIMIT - head.length - tail.length) + tail;
}

// 担当の手番の記録（実行のファイルを gzip したもの）を置き場のリリースへ置き、開くリンクを返す。公開の Actions の記録と成果物は
// 誰でも読めるので、非公開の置き場に置く。1つのリリースに付けられるのは1000件まで（公式の文書「About releases」）なので、
// リリースは日（UTC）ごとに分ける。同じ日の最初の担当どうしが並んで作ると後のほうは作れない（422）ので、先に作られたものへ付ける。
export async function keepLog(gh, repository, { gz, name, now = new Date() }) {
  const day = now.toISOString().slice(0, 10);
  const path = `/repos/${repository}/releases`;
  const find = () => gh.rest("GET", `${path}/tags/turns-${day}`);
  const release = await find().catch(() => gh.rest("POST", path, { tag_name: `turns-${day}`, name: `担当の手番の記録 ${day}` }).catch(find));
  const asset = await gh.rest("POST", `${release.upload_url.replace(/\{.*\}$/, "")}?name=${encodeURIComponent(name)}`, gz, "application/gzip");
  return asset.browser_download_url;
}
