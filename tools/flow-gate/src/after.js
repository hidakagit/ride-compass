// 担当のワークフローの後始末の判断。messages は連携（anthropics/claude-code-action）が書き出す実行のファイル（Agent SDK の
// メッセージの並び）。無ければ null（Claude が起きる前に落ちた）。

const QUOTA = ["rate_limit", "billing_error", "authentication_failed", "oauth_org_not_allowed", "account_on_hold"];
const TRANSIENT = ["overloaded", "server_error"];

// 担当の終わり方の見分け（{ reason, pause }）。作る担当のタスクが進行中のまま終わったら、どの終わり方でも未着手へ戻し（見回りが
// 振り出すか・待つかを決める）、reason はその理由。利用の上限・認証は、続けて起こしても同じく止まるので、どちらの担当でも
// 振り出しを止める（pause）。
export function settle({ messages, url, jobStatus }) {
  const errors = (messages ?? []).filter((m) => m?.type === "assistant" && m.error).map((m) => m.error);
  const quota = errors.find((e) => QUOTA.includes(e));
  const transient = errors.find((e) => TRANSIENT.includes(e));
  const why = quota ? `Claude の利用の上限か認証で止まった（${quota}）`
    : !messages ? "担当が動けなかった（実行のファイルが無い）"
    : transient ? `Claude のサーバーの一時の失敗で止まった（${transient}）`
    : `Pull Request も問いも出さずに終わった（結果: ${jobStatus}）`;
  return { pause: Boolean(quota), reason: `Actions の作る担当（実行 ${url}）が${why}。未着手へ戻す` };
}

// issue へ書く「終わり」のコメント。その回にやったことの要約で、後から人と後の担当が読んで確かめる（docs/architecture/task-flow.md「担当のワークフローの1回」）。担当の最後の
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
