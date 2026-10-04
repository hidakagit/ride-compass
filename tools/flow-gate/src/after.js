// 担当のワークフローの後始末の判断。messages は連携（anthropics/claude-code-action）が書き出す実行のファイル（Agent SDK の
// メッセージの並び）。無ければ null（Claude が起きる前に落ちた）。
import { waitsUntil } from "./rules.js";

const QUOTA = ["rate_limit", "billing_error", "authentication_failed", "oauth_org_not_allowed", "account_on_hold"];
const TRANSIENT = ["overloaded", "server_error"];

// 担当の終わり方の見分け（{ to, reason, pause }）。to と reason は、作る担当のタスクが進行中のまま終わったときの行き先。
// 利用の上限・認証は、続けて起こしても同じく止まるので、どちらの担当でも振り出しを止める（pause）。一時の失敗と Claude が
// 起きる前に落ちたときは、戻すだけ。持ち時間を超えた・Cancel された（ジョブの結果 cancelled）は担当の側の止まりなので落ちた。
export function settle(config, { messages, startOn, url, jobStatus, now = new Date() }) {
  const errors = jobStatus === "cancelled" ? [] : (messages ?? []).filter((m) => m?.type === "assistant" && m.error).map((m) => m.error);
  const quota = errors.find((e) => QUOTA.includes(e));
  const failed = quota ? `Claude の利用の上限か認証で止まった（${quota}）`
    : !messages && jobStatus !== "cancelled" ? "担当が動けなかった（実行のファイルが無い）"
    : errors.find((e) => TRANSIENT.includes(e)) ? `Claude のサーバーの一時の失敗で止まった（${errors.find((e) => TRANSIENT.includes(e))}）` : null;
  if (failed) return { to: config.todo, pause: Boolean(quota), reason: `Actions の作る担当（実行 ${url}）が${failed}。担当の仕事の外の失敗なので未着手へ戻す` };
  const until = waitsUntil(startOn, now);
  if (until) return { to: config.todo, reason: `Actions の作る担当（実行 ${url}）が、着手可能日 ${until} を入れて終えた。その日まで待つので未着手へ戻す` };
  return { to: config.hold, reason: `Actions の作る担当（実行 ${url}）が、Pull Request も問いも出さずに終わった（結果: ${jobStatus}）` };
}

// issue へ書く「終わり」のコメント。置き場は非公開なので担当の最後の発言を書いてよい（公開の Actions の記録には出さない）。
export function endReport({ kind, url, jobStatus, messages, done, status, elapsedMs }) {
  const result = messages?.findLast((m) => m?.type === "result");
  const said = messages?.filter((m) => m?.type === "assistant").map((m) => (m.message?.content ?? []).filter((c) => c?.type === "text").map((c) => c.text).join("\n").trim()).findLast(Boolean);
  const words = ((typeof result?.result === "string" && result.result.trim()) || said || "（無い）").slice(0, 2000);
  const denied = (result?.permission_denials ?? []).map((d) => `${d.tool_name}: ${String(d.tool_input?.command ?? d.tool_input?.file_path ?? d.tool_input?.url ?? "").replace(/\s+/g, " ").slice(0, 100)}`);
  const cell = (s) => String(s).replaceAll("|", "\\|");
  return [
    `### ${kind}担当の終わり`, "", "| | |", "|---|---|",
    `| 終わったときのステータス | ${status ?? "不明"} |`,
    `| 後始末がしたこと | ${done.length ? done.map(cell).join("<br>") : "なし"} |`,
    `| ジョブの結果 | ${jobStatus} |`,
    `| かかった時間（実行の開始から） | ${elapsedMs == null ? "不明" : `${Math.round(elapsedMs / 60000)}分`} |`,
    `| 手数 | ${result?.num_turns ?? "不明"} |`,
    `| 判定に断られた操作 | ${result ? `${denied.length}件${denied.map((d) => `<br>${cell(d)}`).join("")}` : "不明"} |`,
    `| 実行 | ${url} |`, "", "担当の最後の発言:", "", words.split("\n").map((l) => `> ${l}`).join("\n"),
  ].join("\n");
}
